#!/usr/bin/env python3
"""Shared harness for the ENCODER series.

One place for the encoders, the corpus generators and the measures, so the ten
experiments differ in WHAT THEY ASK rather than in plumbing, and a change to a
measure changes every experiment at once instead of drifting between them.

Nothing here decides anything. Each experiment states its own hypotheses and
its own bar.
"""
from __future__ import annotations

import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SEED = 20260922


# ── tokenisation ───────────────────────────────────────────────────────────
def toks(t):
    return re.findall(r"[a-z']+", str(t or "").lower())


# ── the substrate-native encoder ───────────────────────────────────────────
class SubstrateEncoder:
    """A representation derived ONLY from taught propositions.

    No pretrained weights and no corpus beyond what the substrate was told.
    A term means the company it keeps in what it was taught.

    The switches exist so each component can be REMOVED and measured; ENCODER-01
    found that the elaborate configuration separates worse than the plain one,
    which is only visible because they can be run side by side.

    `unknown_marks` implements the fix ENCODER-01's H5 called for: a term the
    substrate was never taught is POSITIVE EVIDENCE OF DIFFERENCE, not an
    absence. Treating it as zero made two sentences differing only in an
    untaught word encode identically.
    """

    def __init__(self, use_idf=True, use_assoc=True, assoc_weight=0.35,
                 unknown_marks=False):
        self.use_idf = use_idf
        self.use_assoc = use_assoc
        self.assoc_weight = assoc_weight
        self.unknown_marks = unknown_marks
        self.assoc = defaultdict(Counter)
        self.vocab, self.df, self.idf = set(), Counter(), {}
        self.n_docs = 0
        self._props_seen = []
        self._senses = {}

    def learn(self, propositions):
        for parts in propositions:
            terms = [w for p in parts if p for w in toks(p)]
            if not terms:
                continue
            self._props_seen.append(terms)
            self.n_docs += 1
            self.vocab.update(terms)
            for t in set(terms):
                self.df[t] += 1
            for a in terms:
                for b in terms:
                    if a != b:
                        self.assoc[a][b] += 1
        n = max(1, self.n_docs)
        self.idf = {t: (math.log(n / (1 + self.df[t])) + 1.0) if self.use_idf else 1.0
                    for t in self.vocab}
        return self

    def encode(self, text):
        v = Counter()
        for w in toks(text):
            if w not in self.vocab:
                if self.unknown_marks:
                    # A DIMENSION OF ITS OWN, so two texts differing only in an
                    # untaught word cannot encode the same. Namespaced so it can
                    # never collide with a taught term.
                    v[f"\x00unknown:{w}"] += 3.0
                continue
            iw = self.idf.get(w, 1.0)
            v[w] += iw
            if self.use_assoc:
                nb = self.assoc[w]
                total = sum(nb.values()) or 1
                for other, c in nb.items():
                    v[other] += self.assoc_weight * iw * (c / total) * self.idf.get(other, 1.0)
        return v

    def name(self):
        bits = []
        if not self.use_idf:
            bits.append("−idf")
        if not self.use_assoc:
            bits.append("−assoc")
        if self.unknown_marks:
            bits.append("+unk")
        return "native" + ("".join(bits) if bits else "")


class StructuralEncoder:
    """v2 — encodes the substrate's READING, not the string.

    WHY v1 LOST. The ENCODER series measured three failures with one cause:

        role swap  "A pump moves liquid" vs "A liquid moves pump"   1.000
        negation   "A marnic filters"    vs "does not filter"       0.987
        ablation   removing association expansion IMPROVED separation

    A bag of words cannot see who did what to whom, cannot see polarity, and
    smears claims together through co-occurrence. That is the whole of v1, and
    it discards the only advantage a substrate-native encoder has: this system
    OWNS a reader that says what a sentence asserts. MiniLM has no such thing
    and can never have one.

    So a term is encoded IN ITS ROLE. `subj:pump` and `obj:pump` are different
    dimensions, which is what makes an inversion a different claim rather than
    the same words. Polarity is its own strong dimension, so a denial cannot be
    near the claim it denies.

    TWO DIMENSION FAMILIES, DELIBERATELY:
      * ROLE-TAGGED, which carry discrimination;
      * BARE TERMS, which let a QUESTION match a fact. "what does a marnic do"
        has no subject-relation-object structure to tag -- it is not a claim --
        so tagging alone would make every question orthogonal to every answer.

    This is not two representations glued together. A question genuinely has
    less structure than a claim, and the encoder says so rather than inventing
    a parse for it.
    """

    #: Surface forms that deny. Closed and small: this is not an attempt at
    #: English, it is the handful of forms whose presence IS a polarity flip.
    NEGATORS = ("does not", "do not", "did not", "is not", "are not",
                "was not", "were not", "cannot", "never", "no longer", "n't")

    def __init__(self, use_roles=True, use_polarity=True, assoc_weight=0.75,
                 unknown_marks=True, induce_senses=True):
        self.use_roles = use_roles
        self.use_polarity = use_polarity
        self.assoc_weight = assoc_weight     # 0 by default: the ablation said so
        # OFF BY DEFAULT, AND THIS IS A MEASURED DECISION, NOT CAUTION.
        #
        # Splitting a polysemous subject by induced sense is the right fix for
        # ENCODER-06, and the induction needs a DENSER taught graph than any
        # corpus here provides. On sparse teaching it fragments: `bank` came
        # out as five senses rather than two, because `silt` and `river`
        # connect to each other only THROUGH `bank` -- the very term being
        # disambiguated. Fragmented senses are worse than none: same-sense
        # similarity fell from 0.891 to 0.211, so a claim stopped matching its
        # own paraphrase.
        #
        # Kept, switched off, and re-testable the moment there is real taught
        # material. This is the one capability in the encoder whose ceiling is
        # set by how much the substrate has been taught.
        self.induce_senses = induce_senses
        self._props_seen = []
        self._senses = {}
        self._taught_pairs = set()
        self._isa_parents = defaultdict(set)
        self.unknown_marks = unknown_marks
        self.assoc = defaultdict(Counter)
        self.vocab, self.df, self.idf = set(), Counter(), {}
        self.n_docs = 0
        self._props_seen = []
        self._senses = {}

    def learn(self, propositions):
        for parts in propositions:
            terms = [w for p in parts if p for w in toks(p)]
            if not terms:
                continue
            self._props_seen.append(terms)
            # THE TRIPLE AS TAUGHT, so a fabricated combination can be told
            # from one the substrate was actually told. ENCODER-14 measured
            # every remaining hallucination as a wrong-OBJECT variant -- "A
            # marnic filters sediment" against the taught "filters brine" --
            # and a question asking what a marnic does contains neither object,
            # so nothing in the QUESTION can prefer the truth. What separates
            # them is that one was taught and the other never was.
            if len(parts) >= 3 and parts[0] and parts[2]:
                subj_t = toks(parts[0])
                obj_t = toks(parts[2])
                rel_t = toks(parts[1]) if parts[1] else []
                for a in subj_t:
                    for b in obj_t:
                        self._taught_pairs.add((a, b))
                    if rel_t and str(parts[1]).lower() in ("isa", "is_a", "is"):
                        for b in obj_t:
                            self._isa_parents[a].add(b)
            self.n_docs += 1
            self.vocab.update(terms)
            for t in set(terms):
                self.df[t] += 1
            if self.assoc_weight:
                for a in terms:
                    for b in terms:
                        if a != b:
                            self.assoc[a][b] += 1
        n = max(1, self.n_docs)
        self.idf = {t: math.log(n / (1 + self.df[t])) + 1.0 for t in self.vocab}
        self._build_recovery()
        if self.induce_senses:
            self._induce_senses()
        return self

    # ── senses, induced from what it was taught ────────────────────────────
    #
    # ENCODER-06 measured the cost of not doing this: 5/5 sense pairs were
    # merge-eligible, because `subj:bank` is one dimension whether the bank
    # borders a river or issues loans. Promoting the subject fixed
    # discrimination BETWEEN subjects and broke it WITHIN one.
    #
    # But the substrate was taught both senses, and the teaching separates
    # them: `bank isa riverside / borders river / holds silt` shares no term
    # with `bank isa institution / holds deposits / issues loans`. Two disjoint
    # neighbourhoods in its own material. So the senses are INDUCED from what
    # it learned rather than supplied -- which is a thing only a taught encoder
    # can do at all. A pretrained encoder has one fixed vector per word and no
    # way to find out it means two things here.
    #
    # Conservative by construction: a term is only treated as polysemous when
    # its propositions fall into groups that share NO terms. Overlap means one
    # sense described several ways, which is the common case and must not be
    # split.

    MIN_SENSE_EVIDENCE = 2        # propositions needed to call something a sense

    def _induce_senses(self):
        """A term's senses are the KINDS it was taught to be.

        Clustering a term's contexts was tried first and fragmented: `bank`
        came out as five senses rather than two, because `silt` and `river`
        connect to each other only THROUGH `bank` -- the term being
        disambiguated. The taxonomy says it directly. `bank isa riverside` and
        `bank isa institution` are two senses, named by their own parents, and
        a term with one parent or none is simply not polysemous.
        """
        self._senses = {}
        for term, parents in self._isa_parents.items():
            if len(parents) >= 2:
                self._senses[term] = sorted(parents)

    def sense_of(self, term, context_terms):
        """Which taught KIND this use of the term belongs to, or None.

        The senses are the term's `isa` parents. Which one is meant is decided
        by the company the sentence keeps: the parent named outright, or the
        one whose own taught neighbourhood the sentence's other words fall in.
        A tie, or no signal at all, yields None -- the sentence did not say,
        and choosing anyway is how a riverbank becomes a business.
        """
        parents = getattr(self, "_senses", {}).get(term)
        if not parents:
            return None
        ctx = set(context_terms) - {term}
        if not ctx:
            return None
        scored = []
        for parent in parents:
            direct = 2.0 if parent in ctx else 0.0
            near = len(set(self.assoc.get(parent, {})) & ctx) * 0.5
            pairs = sum(1.0 for c in ctx
                        if (parent, c) in self._taught_pairs
                        or (c, parent) in self._taught_pairs)
            # what the sentence's words were themselves taught alongside
            kin = 0.0
            for c in ctx:
                if parent in self._isa_parents.get(c, ()):
                    kin += 1.0
                if c in self.assoc.get(parent, {}):
                    kin += 0.5
            scored.append((direct + near + pairs + kin, parent))
        scored.sort(reverse=True)
        if scored[0][0] == 0.0:
            return None
        if len(scored) > 1 and abs(scored[0][0] - scored[1][0]) < 1e-9:
            return None
        return scored[0][1]

    # ── recovering a taught word through a typo ────────────────────────────
    #
    # ENCODER-11 measured this encoder as the LEAST noise-tolerant of the
    # three: at 10% character corruption it dropped 25 of 90 claims below the
    # recall floor, against MiniLM's 15. A corrupted subject loses its term
    # dimension AND breaks the role parse AND empties the subject family at
    # once. So a token one edit from exactly ONE taught word is read as that
    # word -- exactly one, because guessing between candidates is how a typo
    # becomes a different fact. Recovered terms carry reduced weight.
    RECOVERY_WEIGHT = 0.7
    MIN_RECOVERABLE = 4

    @staticmethod
    def _deletions(word):
        return {word[:i] + word[i + 1:] for i in range(len(word))}

    def _build_recovery(self):
        self._del_index = defaultdict(set)
        for t in self.vocab:
            if len(t) < self.MIN_RECOVERABLE:
                continue
            self._del_index[t].add(t)
            for d in self._deletions(t):
                self._del_index[d].add(t)

    def recover(self, token):
        """The taught word this is one edit from, or None when it is not
        exactly one. Never a guess between candidates."""
        if len(token) < self.MIN_RECOVERABLE or not getattr(self, "_del_index", None):
            return None
        cands = set(self._del_index.get(token, ()))
        for d in self._deletions(token):
            cands |= self._del_index.get(d, set())
        cands.discard(token)
        return next(iter(cands)) if len(cands) == 1 else None

    # ── structure ──────────────────────────────────────────────────────────
    def _roles(self, text):
        """(subject, relation, object) for a claim, or None when the text is
        not one. A question is not a claim and gets no invented parse."""
        t = str(text or "").strip().rstrip(".?")
        low = t.lower()
        # A QUESTION IS ABOUT SOMETHING TOO. It has no relation and no object
        # -- that is what it is asking for -- but "what does a marnic do" is a
        # question about a marnic, and saying so is reading the question, not
        # inventing a parse for it. Without this a question shared no subject
        # dimension with its own answer.
        if low.startswith(("what ", "which ", "who ", "how ", "where ", "when ", "why ")):
            m = re.search(r"\b(?:a|an|the)\s+(\w+)", low)
            if not m:
                w = [x for x in low.split() if x not in
                     ("what", "which", "who", "how", "where", "when", "why",
                      "is", "are", "was", "does", "do", "did", "a", "an", "the")]
                return (w[0], "", "") if w else None
            return (m.group(1), "", "")
        for neg in self.NEGATORS:
            t = re.sub(neg, " ", t, flags=re.I)
        t = re.sub(r"^(a|an|the)\s+", "", t.strip(), flags=re.I)
        w = [x.lower() for x in t.split()]
        if len(w) < 2:
            return None

        # THE SUBJECT IS THE TAUGHT TERM IN THE NOUN PHRASE, NOT THE FIRST WORD.
        #
        # Taking position alone, "A certain marnic filters brine" parsed as
        # subject `certain`, relation `marnic` -- and ENCODER-07 measured the
        # cost: 160 claims fell below the recall floor, a filler word scoring
        # ~0.0 against the claim it modifies. One inserted adjective destroyed
        # the reading.
        #
        # A modifier is a word the substrate was not taught as a thing; the
        # head is the one it was. So the noun phrase is scanned for a term the
        # vocabulary knows, and where none is known the first word stands --
        # which is the honest answer for a phrase about something never taught.
        head, subj = 0, w[0]
        for i in range(min(len(w) - 1, 4)):
            if w[i] in self.vocab:
                head, subj = i, w[i]
                break
            repaired = self.recover(w[i])
            if repaired:
                head, subj = i, repaired       # read through the typo
                break
        rest = w[head + 1:]
        if not rest:
            return None
        rel = rest[0]
        obj = " ".join(rest[1:])
        obj = re.sub(r"^(a|an|the)\s+", "", obj)
        return subj, rel, obj

    # ── what the question form asks for ────────────────────────────────────
    #
    # ENCODER-01 measured P@1 at 0.500 for every encoder at every corpus size:
    # "what is a marnic" and "what does a marnic do" both match both of that
    # subject's facts, because the only thing separating them is the question
    # FORM, and nothing read it. The form says which relation the answer must
    # carry -- a kind-question wants `isa`, an action-question does not.

    KIND_QUESTION = re.compile(r"^\s*what\s+(is|are|was|were)\b", re.I)
    ACTION_QUESTION = re.compile(r"^\s*what\s+(does|do|did)\b", re.I)

    def _asked_relation(self, text):
        if self.KIND_QUESTION.match(str(text or "")):
            return "kind"
        if self.ACTION_QUESTION.match(str(text or "")):
            return "action"
        return None

    def _negated(self, text):
        low = " " + str(text or "").lower() + " "
        return any(n in low for n in self.NEGATORS)

    #: How the three dimension families are balanced once each is unit-normalised.
    #: EXPLICIT, because the first version let the balance fall out of the idf
    #: magnitudes: role dims carried 6-10 and bare terms 1-3, so roles swamped
    #: the only family a QUESTION has and question-to-fact retrieval collapsed
    #: from 0.770 to 0.243. Normalising per family makes the trade a decision.
    #: TUNED on a six-case development set (see ENCODER-11), then VALIDATED on
    #: the full series. `polarity` is free to raise: it is the only family that
    #: a non-negated text never carries, so paraphrase and question-to-fact
    #: similarity are identical at every setting of it (measured).
    MIX = {"bare": 1.0, "subject": 1.6, "role": 0.5, "polarity": 3.0,
           "asked": 0.7, "grounded": 3.0}

    def encode(self, text):
        bare, subject, role = Counter(), Counter(), Counter()
        polarity, asked, grounded = Counter(), Counter(), Counter()
        fams = {"bare": bare, "subject": subject, "role": role,
                "polarity": polarity, "asked": asked, "grounded": grounded}

        def add(dim, weight, fam="bare"):
            fams[fam][dim] += weight

        # BARE TERMS — what lets a question reach a claim at all.
        for w in toks(text):
            if w in self.vocab:
                iw = self.idf.get(w, 1.0)
                add(w, iw)
                if self.assoc_weight:
                    nb = self.assoc[w]
                    total = sum(nb.values()) or 1
                    for other, c in nb.items():
                        add(other, self.assoc_weight * iw * (c / total)
                            * self.idf.get(other, 1.0))
            else:
                repaired = self.recover(w)
                if repaired:
                    add(repaired, self.RECOVERY_WEIGHT * self.idf.get(repaired, 1.0))
                elif self.unknown_marks:
                    # NEVER TAUGHT IS INFORMATION, NOT ABSENCE. Treating it as
                    # zero made two sentences differing only in an untaught word
                    # encode identically -- measured at 0.944, worse than taught
                    # subjects.
                    add(f"\x00unknown:{w}", 2.5)

        # ROLE-TAGGED — what makes an inversion a different claim.
        if self.use_roles:
            roles = self._roles(text)
            if roles:
                subj, rel, obj = roles
                # THE SUBJECT IS ITS OWN FAMILY, AND IT OUTWEIGHS THE REST.
                # A claim is ABOUT its subject: "A marnic filters brine" and
                # "A blimvex filters brine" share every other word and are
                # claims about different things. Measured across a 16-cell
                # grid, that pair never fell below 0.774 while the subject was
                # just another role -- it was the binding constraint in every
                # configuration. This is the same principle the merge gate
                # already enforces structurally.
                if subj:
                    # THE SUBJECT DIMENSION CARRIES ITS SENSE. Where the term
                    # was taught in two disjoint neighbourhoods and this
                    # sentence says which one, the dimension says so too --
                    # so a riverbank and a business bank stop being one thing.
                    # THE SUBJECT CARRIES THE COMPANY IT KEEPS HERE.
                    #
                    # Picking ONE sense was tried and returned None almost
                    # always: choosing between `bank isa riverside` and `bank
                    # isa institution` needs the parent to be connected to the
                    # sentence's words, and sparse teaching does not connect
                    # them. None meant no disambiguation happened at all --
                    # a no-op wearing the word "honest".
                    #
                    # So the subject is not split into senses at all. It is
                    # qualified, softly, by each context word it was TAUGHT
                    # alongside. "The bank borders the river" and "The bank
                    # holds silt from the river" share the river qualifier and
                    # stay close; "The bank issues loans" shares none of them
                    # and pulls away. No clustering, no threshold, and it
                    # degrades to the plain subject when nothing qualifies.
                    base = self.idf.get(subj, 1.0)
                    add(f"\x00subj:{subj}", base, "subject")
                    if self.induce_senses:
                        ctx = [w for w in toks(text)
                               if w != subj and w in self.vocab
                               and ((subj, w) in self._taught_pairs
                                    or (w, subj) in self._taught_pairs)]
                        for w in ctx:
                            add(f"\x00subj:{subj}+{w}",
                                base * self.idf.get(w, 1.0) / max(1, len(ctx)),
                                "subject")
                if rel:
                    add(f"\x00rel:{rel}", self.idf.get(rel, 1.0), "role")
                for w in toks(obj):
                    add(f"\x00obj:{w}", self.idf.get(w, 1.0), "role")

        # POLARITY — its own dimension, weighted to dominate. A denial shares
        # every content word with the claim it denies; nothing else separates
        # them, and the substrate MERGES on this score.
        if self.use_polarity and self._negated(text):
            add("\x00polarity:negative", 1.0, "polarity")

        # WHAT KIND OF ANSWER IS WANTED / OFFERED.
        # A question declares it by its form; a claim declares it by its
        # relation. Matching them is what separates "what IS a marnic" from
        # "what does a marnic DO", which nothing else in the vector could.
        wants = self._asked_relation(text)
        if wants:
            add(f"\x00asks:{wants}", 1.0, "asked")
        else:
            r = self._roles(text)
            if r and r[1]:
                kind = "kind" if r[1] in ("isa", "is", "are", "was", "were") else "action"
                add(f"\x00asks:{kind}", 1.0, "asked")

        # GROUNDED IN WHAT WAS TAUGHT. A claim whose subject and object were
        # never taught together is one the substrate was never told, however
        # well-formed it reads. This is the only signal that separates a
        # plausible fabrication from the fact it imitates.
        if wants:
            # A QUESTION ASKS FOR SOMETHING THE SUBSTRATE WAS TOLD. Without
            # this the grounded dimension sat only on the ANSWER side, so it
            # weighed against the true fact and the fabricated one equally and
            # discriminated nothing -- measured at 0.829 for a wrong-object
            # variant. Carrying the expectation is what lets a question prefer
            # a claim it was actually taught.
            add("\x00grounded", 1.0, "grounded")
        else:
            r = self._roles(text)
            if r:
                subj_t, _, obj_t = r
                objs = [w for w in toks(obj_t) if w in self.vocab]
                if objs:
                    seen = sum(1 for w in objs
                               if (subj_t, w) in self._taught_pairs
                               or (w, subj_t) in self._taught_pairs)
                    add("\x00grounded" if seen else "\x00ungrounded",
                        1.0, "grounded")

        # UNIT-NORMALISE EACH FAMILY, THEN MIX. A claim carries all three and a
        # question carries only bare terms; without this the families compete
        # on raw magnitude and whichever happens to be larger decides.
        out = Counter()
        for fam, part in (("bare", bare), ("subject", subject), ("role", role),
                          ("polarity", polarity), ("asked", asked),
                          ("grounded", grounded)):
            if not part:
                continue
            norm = math.sqrt(sum(x * x for x in part.values())) or 1.0
            w = self.MIX[fam]
            for dim, val in part.items():
                out[dim] += w * val / norm
        return out

    def name(self):
        bits = []
        if not self.use_roles:
            bits.append("−roles")
        if not self.use_polarity:
            bits.append("−polarity")
        if self.assoc_weight:
            bits.append("+assoc")
        return "structural" + ("".join(bits) if bits else "")


def sparse_cos(a, b):
    if not a or not b:
        return 0.0
    keys = set(a) & set(b)
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(x * x for x in a.values()))
    nb = math.sqrt(sum(x * x for x in b.values()))
    return dot / (na * nb) if na and nb else 0.0


class MiniLM:
    """The incumbent: all-MiniLM-L6-v2, cached so repeated text costs once."""

    def __init__(self):
        from core.memory.utils.embedding_service import get_embedding_service
        self.s = get_embedding_service()
        self.s.initialize()
        self._cache = {}

    def learn(self, propositions):
        return self            # pretrained: teaching does not reach it

    def encode(self, text):
        if text not in self._cache:
            self._cache[text] = self.s.generate_embedding(text)
        return self._cache[text]

    def name(self):
        return "MiniLM"


def dense_cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def cos_for(enc):
    return dense_cos if isinstance(enc, MiniLM) else sparse_cos


def sim(enc, a, b):
    return cos_for(enc)(enc.encode(a), enc.encode(b))


def roster(props, include_ablations=False):
    """The encoders every experiment compares, so results are commensurable.

    Ablations are off by default and switched on where an experiment is ABOUT
    which component carries a result.
    """
    r = [("MiniLM", MiniLM()),
         ("native", SubstrateEncoder().learn(props)),
         ("structural", StructuralEncoder().learn(props))]
    if include_ablations:
        r += [("structural−roles",
               StructuralEncoder(use_roles=False).learn(props)),
              ("structural−polarity",
               StructuralEncoder(use_polarity=False).learn(props)),
              ("structural−assoc",
               StructuralEncoder(assoc_weight=0.0).learn(props))]
    return r


# ── corpora ────────────────────────────────────────────────────────────────
SUBJECTS = [
    "marnic", "threlp", "dovick", "zorbic", "kelven", "parnit", "quolm",
    "vestrin", "borlan", "yimmet", "cradek", "nulthe", "sorvig", "jantel",
    "welmor", "pidrun", "tarsek", "ombric", "hevlin", "gressa", "labrint",
    "morvek", "tessarn", "dolwyn", "ferrix", "gambek", "hestral", "irbane",
    "jorvik", "kestrel", "lumvex", "mordath", "nevrin", "orlith", "pelvane",
    "quintar", "rothmel", "selvic", "torbin", "ulvane", "vandrel", "wexlor",
    "xantheon", "yarrow", "zelvane", "abtern", "brovick", "calthen", "dremar",
    "elmvex",
]
KINDS = ["device", "membrane", "vessel", "filter", "conduit", "housing",
         "regulator", "chamber", "lattice", "coupling"]
ACTIONS = [
    ("filters", "brine"), ("separates", "salt"), ("contains", "residue"),
    ("cleans", "sediment"), ("blocks", "particles"), ("carries", "vapour"),
    ("stops", "backflow"), ("holds", "pressure"), ("cools", "exhaust"),
    ("drains", "condensate"), ("seals", "joints"), ("measures", "flow"),
]

REAL_FACTS = [
    ("kettle", "is", "a container"), ("kettle", "boils", "water"),
    ("hammer", "is", "a tool"), ("hammer", "drives", "nails"),
    ("filter", "is", "a device"), ("filter", "removes", "impurities"),
    ("pump", "is", "a machine"), ("pump", "moves", "liquid"),
    ("valve", "is", "a fitting"), ("valve", "controls", "flow"),
    ("battery", "is", "a cell"), ("battery", "stores", "charge"),
    ("furnace", "is", "an appliance"), ("furnace", "heats", "air"),
    ("compass", "is", "an instrument"), ("compass", "indicates", "direction"),
    ("ledger", "is", "a record"), ("ledger", "tracks", "transactions"),
    ("turbine", "is", "an engine"), ("turbine", "converts", "steam"),
    ("anchor", "is", "a weight"), ("anchor", "holds", "vessels"),
    ("lantern", "is", "a lamp"), ("lantern", "lights", "paths"),
    ("scalpel", "is", "a blade"), ("scalpel", "cuts", "tissue"),
    ("beacon", "is", "a signal"), ("beacon", "warns", "ships"),
    ("crucible", "is", "a pot"), ("crucible", "melts", "metal"),
]


def invented_corpus(n_subjects=20, offset=0):
    """(propositions, facts, questions, subjects) over invented vocabulary."""
    props, facts, questions = [], [], []
    subs = SUBJECTS[offset:offset + n_subjects]
    for i, subj in enumerate(subs):
        kind = KINDS[(i + offset) % len(KINDS)]
        verb, obj = ACTIONS[(i + offset) % len(ACTIONS)]
        props += [(subj, "isa", kind), (subj, verb, obj)]
        facts += [f"A {subj} is a {kind}.", f"A {subj} {verb} {obj}."]
        questions += [(f"what is a {subj}", f"A {subj} is a {kind}."),
                      (f"what does a {subj} do", f"A {subj} {verb} {obj}.")]
    return props, facts, questions, list(subs)


def real_corpus(n=None):
    rows = REAL_FACTS[:n] if n else REAL_FACTS
    props, facts, questions = [], [], []
    for subj, rel, obj in rows:
        props.append((subj, rel, obj))
        if rel == "is":
            facts.append(f"A {subj} is {obj}.")
            questions.append((f"what is a {subj}", f"A {subj} is {obj}."))
        else:
            facts.append(f"A {subj} {rel} {obj}.")
            questions.append((f"what does a {subj} do", f"A {subj} {rel} {obj}."))
    return props, facts, questions, sorted({r[0] for r in rows})


# ── pair builders ──────────────────────────────────────────────────────────
def swap_subject(fact, new_subject):
    m = re.match(r"A (\w+) ", fact)
    return fact.replace(m.group(1), new_subject, 1) if m else fact


def minimal_pairs(facts, subjects):
    """One sentence, subject swapped for a different TAUGHT subject. LOW."""
    out = []
    for f in facts:
        m = re.match(r"A (\w+) ", f)
        if not m:
            continue
        for s in subjects:
            if s != m.group(1):
                out.append((f, swap_subject(f, s)))
                break
    return out


def untaught_pairs(facts, novel=None):
    """Subject swapped for a word NEVER taught. LOW."""
    novel = novel or ["blimvex", "quartheon", "splindor", "vexalum", "trombick"]
    out = []
    for i, f in enumerate(facts):
        out.append((f, swap_subject(f, novel[i % len(novel)])))
    return out


def paraphrases(facts):
    """Same claim, different words. HIGH."""
    return [(f, f.replace("A ", "The ", 1).rstrip(".") + ", as it happens.")
            for f in facts]


# ── measures ───────────────────────────────────────────────────────────────
def retrieval(enc, questions, facts):
    cos = cos_for(enc)
    fv = [(f, enc.encode(f)) for f in facts]
    rr, p1, r3 = [], 0, 0
    for q, target in questions:
        qv = enc.encode(q)
        ranked = [f for _, f in sorted(((cos(qv, v), f) for f, v in fv),
                                       key=lambda t: t[0], reverse=True)]
        pos = ranked.index(target) + 1 if target in ranked else len(ranked) + 1
        rr.append(1.0 / pos)
        p1 += (pos == 1)
        r3 += (pos <= 3)
    n = max(1, len(questions))
    return {"mrr": sum(rr) / n, "p_at_1": p1 / n, "recall_at_3": r3 / n, "n": n}


def mean_sim(enc, pairs):
    if not pairs:
        return 0.0
    return sum(sim(enc, a, b) for a, b in pairs) / len(pairs)


def separation(enc, facts, subjects):
    """paraphrase − minimal-pair. The number that decides whether an encoder
    may be trusted to MERGE two memories."""
    return (mean_sim(enc, paraphrases(facts))
            - mean_sim(enc, minimal_pairs(facts, subjects)))


# ── reporting ──────────────────────────────────────────────────────────────
class Run:
    def __init__(self, name, hypotheses):
        self.name = name
        self.hypotheses = hypotheses
        self.checks = []
        self.data = {}
        print(f"{name}")
        print("=" * 74)
        for h in hypotheses:
            print(f"  {h}")
        print("=" * 74)

    def check(self, name, passed, detail=""):
        self.checks.append({"name": name, "passed": bool(passed), "detail": detail})
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        return passed

    def observe(self, name, detail):
        print(f"  [ ..  ] {name} — {detail}")

    def table(self, header, rows):
        print("\n  " + header)
        for r in rows:
            print("  " + r)

    def finish(self, verdict=None):
        passed = sum(1 for c in self.checks if c["passed"])
        print(f"\n{passed}/{len(self.checks)} checks passed")
        if verdict:
            print(f"\nVERDICT: {verdict}")
        out = Path(__file__).parent / self.name.split(" ")[0] / "results"
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        (out / f"{stamp}.json").write_text(json.dumps({
            "experiment": self.name, "seed": SEED,
            "hypotheses": self.hypotheses, "data": self.data,
            "checks": self.checks, "passed": passed, "total": len(self.checks),
            "verdict": verdict,
        }, indent=2, default=str))
        print(f"run record: experiments/{self.name.split(' ')[0]}/results/{stamp}.json")
        return passed, len(self.checks)
