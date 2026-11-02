"""The English Resource Grammar's meanings said in Lyric's meaning language (`core/semantics/erg_meanings.py`).

WHAT STANDS OVER A CLAUSE is what these check: a denial, a hedge and a condition are all written by the ERG as a
predicate taking the clause as its place, and each has to reach Lyric's own field for it -- `has_property(e, false)`
for a happening denied, `MeaningFact.positive` for a link denied, `unasserted` for what the sentence does not tell
as so, `condition` for what must hold first. Read a level at a time they landed on the wrong thing: "Jordan might
not be an administrator." came out saying he IS one (2026-11-02).

NO ACE AND NO DOCKER HERE. Each sentence's Minimal Recursion Semantics is what ACE 0.9.34 with the ERG 2018 read of
it, kept here as it came (`READ`), so what is tested is the bridge and nothing else.
"""
import pytest
from delphin import eds
from delphin.codecs import simplemrs

from core.semantics import erg_meanings as em

#: EACH SENTENCE'S MINIMAL RECURSION SEMANTICS AS ACE READ IT, kept exactly as it came out of ACE 0.9.34
#: with the ERG 2018 (`experiments/GRAMMAR-01/diagnostics/erg_parse.py`), so these tests need neither.
#: Written here rather than in `test_data/` as `test_pmb_meanings` writes its documents here: the fixture
#: is part of the test, where the corpora under `test_data/semantics/` are not pushed at all.
READ = {
    'If Jordan disables the account, Luis loses his access.':
        '[ LTOP: h0 INDEX: e2 [ e SF: prop TENSE: pres MOOD: indicative PROG: - PERF: - ] RELS: < [ _if_x_then<0:2> LBL: '
        'h1 ARG0: e4 [ e SF: prop TENSE: untensed MOOD: indicative PROG: - PERF: - ] ARG1: h5 ARG2: h6 ]  [ proper_q<3:9> '
        'LBL: h7 ARG0: x8 [ x PERS: 3 NUM: sg IND: + ] RSTR: h9 BODY: h10 ]  [ named<3:9> LBL: h11 CARG: "Jordan" ARG0: '
        'x8 ]  [ _disable_v_1<10:18> LBL: h13 ARG0: e14 [ e SF: prop TENSE: pres MOOD: indicative PROG: - PERF: - ] ARG1: '
        'x8 ARG2: x15 [ x PERS: 3 NUM: sg IND: + ] ]  [ _the_q<19:22> LBL: h16 ARG0: x15 RSTR: h17 BODY: h18 ]  [ '
        '_account_n_of<23:31> LBL: h19 ARG0: x15 ARG1: i20 ]  [ proper_q<32:36> LBL: h21 ARG0: x3 [ x PERS: 3 NUM: sg '
        'IND: + ] RSTR: h22 BODY: h23 ]  [ named<32:36> LBL: h24 CARG: "Luis" ARG0: x3 ]  [ _lose_v_1<37:42> LBL: h26 '
        'ARG0: e2 ARG1: x3 ARG2: x27 [ x PERS: 3 NUM: sg ] ]  [ def_explicit_q<43:46> LBL: h28 ARG0: x27 RSTR: h29 BODY: '
        'h30 ]  [ poss<43:46> LBL: h31 ARG0: e32 [ e SF: prop TENSE: untensed MOOD: indicative PROG: - PERF: - ] ARG1: '
        'x27 ARG2: x33 [ x PERS: 3 NUM: sg GEND: m IND: + PT: std ] ]  [ pronoun_q<43:46> LBL: h34 ARG0: x33 RSTR: h35 '
        'BODY: h36 ]  [ pron<43:46> LBL: h37 ARG0: x33 ]  [ _access_n_to<47:54> LBL: h31 ARG0: x27 ARG1: i38 ] > HCONS: < '
        'h0 qeq h1 h5 qeq h26 h6 qeq h13 h9 qeq h11 h17 qeq h19 h22 qeq h24 h29 qeq h31 h35 qeq h37 > ICONS: < > ]',
    "Jordan did not disable Luis's account.":
        '[ LTOP: h0 INDEX: e2 [ e SF: prop TENSE: past MOOD: indicative PROG: - PERF: - ] RELS: < [ proper_q<0:6> LBL: h4 '
        'ARG0: x3 [ x PERS: 3 NUM: sg IND: + ] RSTR: h5 BODY: h6 ]  [ named<0:6> LBL: h7 CARG: "Jordan" ARG0: x3 ]  [ '
        'neg<11:14> LBL: h1 ARG0: e9 [ e SF: prop TENSE: untensed MOOD: indicative PROG: - PERF: - ] ARG1: h10 ]  [ '
        '_disable_v_1<15:22> LBL: h11 ARG0: e2 ARG1: x3 ARG2: x12 [ x PERS: 3 NUM: sg IND: + ] ]  [ proper_q<23:27> LBL: '
        'h13 ARG0: x14 [ x PERS: 3 NUM: sg IND: + ] RSTR: h15 BODY: h16 ]  [ named<23:27> LBL: h17 CARG: "Luis" ARG0: x14 '
        ']  [ def_explicit_q<27:29> LBL: h19 ARG0: x12 RSTR: h20 BODY: h21 ]  [ poss<27:29> LBL: h22 ARG0: e23 [ e SF: '
        'prop TENSE: untensed MOOD: indicative PROG: - PERF: - ] ARG1: x12 ARG2: x14 ]  [ _account_n_of<30:38> LBL: h22 '
        'ARG0: x12 ARG1: i24 ] > HCONS: < h0 qeq h1 h5 qeq h7 h10 qeq h11 h15 qeq h17 h20 qeq h22 > ICONS: < > ]',
    'Jordan gave Luis the admin role.':
        '[ LTOP: h0 INDEX: e2 [ e SF: prop TENSE: past MOOD: indicative PROG: - PERF: - ] RELS: < [ proper_q<0:6> LBL: h4 '
        'ARG0: x3 [ x PERS: 3 NUM: sg IND: + ] RSTR: h5 BODY: h6 ]  [ named<0:6> LBL: h7 CARG: "Jordan" ARG0: x3 ]  [ '
        '_give_v_1<7:11> LBL: h1 ARG0: e2 ARG1: x3 ARG2: x9 [ x PERS: 3 NUM: sg IND: + ] ARG3: x10 [ x PERS: 3 NUM: sg '
        'IND: + ] ]  [ proper_q<12:16> LBL: h11 ARG0: x10 RSTR: h12 BODY: h13 ]  [ named<12:16> LBL: h14 CARG: "Luis" '
        'ARG0: x10 ]  [ _the_q<17:20> LBL: h16 ARG0: x9 RSTR: h17 BODY: h18 ]  [ compound<21:32> LBL: h19 ARG0: e20 [ e '
        'SF: prop TENSE: untensed MOOD: indicative PROG: - PERF: - ] ARG1: x9 ARG2: x21 [ x IND: + PT: notpro ] ]  [ '
        'udef_q<21:26> LBL: h22 ARG0: x21 RSTR: h23 BODY: h24 ]  [ _admin_n_1<21:26> LBL: h25 ARG0: x21 ]  [ '
        '_role_n_of<27:32> LBL: h19 ARG0: x9 ARG1: i26 ] > HCONS: < h0 qeq h1 h5 qeq h7 h12 qeq h14 h17 qeq h19 h23 qeq '
        'h25 > ICONS: < > ]',
    "Jordan may have disabled Luis's account.":
        '[ LTOP: h0 INDEX: e2 [ e SF: prop TENSE: pres MOOD: indicative PROG: - PERF: + ] RELS: < [ proper_q<0:6> LBL: h4 '
        'ARG0: x3 [ x PERS: 3 NUM: sg IND: + ] RSTR: h5 BODY: h6 ]  [ named<0:6> LBL: h7 CARG: "Jordan" ARG0: x3 ]  [ '
        '_may_v_modal<7:10> LBL: h1 ARG0: e2 ARG1: h9 ]  [ _disable_v_1<16:24> LBL: h10 ARG0: e11 [ e SF: prop TENSE: '
        'untensed MOOD: indicative PROG: - PERF: + ] ARG1: x3 ARG2: x12 [ x PERS: 3 NUM: sg IND: + ] ]  [ proper_q<25:29> '
        'LBL: h13 ARG0: x14 [ x PERS: 3 NUM: sg IND: + ] RSTR: h15 BODY: h16 ]  [ named<25:29> LBL: h17 CARG: "Luis" '
        'ARG0: x14 ]  [ def_explicit_q<29:31> LBL: h19 ARG0: x12 RSTR: h20 BODY: h21 ]  [ poss<29:31> LBL: h22 ARG0: e23 '
        '[ e SF: prop TENSE: untensed MOOD: indicative PROG: - PERF: - ] ARG1: x12 ARG2: x14 ]  [ _account_n_of<32:40> '
        'LBL: h22 ARG0: x12 ARG1: i24 ] > HCONS: < h0 qeq h1 h5 qeq h7 h9 qeq h10 h15 qeq h17 h20 qeq h22 > ICONS: < > ]',
    'Jordan might not be an administrator.':
        '[ LTOP: h0 INDEX: e2 [ e SF: prop TENSE: pres MOOD: indicative PROG: - PERF: - ] RELS: < [ proper_q<0:6> LBL: h4 '
        'ARG0: x3 [ x PERS: 3 NUM: sg IND: + ] RSTR: h5 BODY: h6 ]  [ named<0:6> LBL: h7 CARG: "Jordan" ARG0: x3 ]  [ '
        '_might_v_modal<7:12> LBL: h9 ARG0: e2 ARG1: h10 ]  [ neg<13:16> LBL: h1 ARG0: e11 [ e SF: prop TENSE: untensed '
        'MOOD: indicative PROG: - PERF: - ] ARG1: h12 ]  [ _be_v_id<17:19> LBL: h13 ARG0: e14 [ e SF: prop TENSE: '
        'untensed MOOD: indicative PROG: - PERF: - ] ARG1: x3 ARG2: x15 [ x PERS: 3 NUM: sg IND: + ] ]  [ _a_q<20:22> '
        'LBL: h16 ARG0: x15 RSTR: h17 BODY: h18 ]  [ _administrator_n_of<23:37> LBL: h19 ARG0: x15 ARG1: i20 ] > HCONS: < '
        'h0 qeq h1 h5 qeq h7 h10 qeq h13 h12 qeq h9 h17 qeq h19 > ICONS: < > ]',
    'Jordan must approve the request.':
        '[ LTOP: h0 INDEX: e2 [ e SF: prop TENSE: pres MOOD: indicative PROG: - PERF: - ] RELS: < [ proper_q<0:6> LBL: h4 '
        'ARG0: x3 [ x PERS: 3 NUM: sg IND: + ] RSTR: h5 BODY: h6 ]  [ named<0:6> LBL: h7 CARG: "Jordan" ARG0: x3 ]  [ '
        '_must_v_modal<7:11> LBL: h1 ARG0: e2 ARG1: h9 ]  [ _approve_v_1<12:19> LBL: h10 ARG0: e11 [ e SF: prop TENSE: '
        'untensed MOOD: indicative PROG: - PERF: - ] ARG1: x3 ARG2: x12 [ x PERS: 3 NUM: sg IND: + ] ]  [ _the_q<20:23> '
        'LBL: h13 ARG0: x12 RSTR: h14 BODY: h15 ]  [ _request_n_for<24:32> LBL: h16 ARG0: x12 ARG1: i17 ] > HCONS: < h0 '
        'qeq h1 h5 qeq h7 h9 qeq h10 h14 qeq h16 > ICONS: < > ]',
    'Jordan removed Luis from the finance team.':
        '[ LTOP: h0 INDEX: e2 [ e SF: prop TENSE: past MOOD: indicative PROG: - PERF: - ] RELS: < [ proper_q<0:6> LBL: h4 '
        'ARG0: x3 [ x PERS: 3 NUM: sg IND: + ] RSTR: h5 BODY: h6 ]  [ named<0:6> LBL: h7 CARG: "Jordan" ARG0: x3 ]  [ '
        '_remove_v_1<7:14> LBL: h1 ARG0: e2 ARG1: x3 ARG2: x9 [ x PERS: 3 NUM: sg IND: + ] ARG3: h10 ]  [ proper_q<15:19> '
        'LBL: h11 ARG0: x9 RSTR: h12 BODY: h13 ]  [ named<15:19> LBL: h14 CARG: "Luis" ARG0: x9 ]  [ _from_p<20:24> LBL: '
        'h16 ARG0: e17 [ e SF: prop TENSE: untensed MOOD: indicative PROG: - PERF: - ] ARG1: x9 ARG2: x18 [ x PERS: 3 '
        'NUM: sg IND: + ] ]  [ _the_q<25:28> LBL: h19 ARG0: x18 RSTR: h20 BODY: h21 ]  [ compound<29:42> LBL: h22 ARG0: '
        'e23 [ e SF: prop TENSE: untensed MOOD: indicative PROG: - PERF: - ] ARG1: x18 ARG2: x24 [ x PT: notpro ] ]  [ '
        'udef_q<29:36> LBL: h25 ARG0: x24 RSTR: h26 BODY: h27 ]  [ _finance_n_1<29:36> LBL: h28 ARG0: x24 ]  [ '
        '_team_n_of<37:42> LBL: h22 ARG0: x18 ARG1: i29 ] > HCONS: < h0 qeq h1 h5 qeq h7 h10 qeq h16 h12 qeq h14 h20 qeq '
        'h22 h26 qeq h28 > ICONS: < > ]',
    'Luis can read the finance data.':
        '[ LTOP: h0 INDEX: e2 [ e SF: prop TENSE: pres MOOD: indicative PROG: - PERF: - ] RELS: < [ proper_q<0:4> LBL: h4 '
        'ARG0: x3 [ x PERS: 3 NUM: sg IND: + ] RSTR: h5 BODY: h6 ]  [ named<0:4> LBL: h7 CARG: "Luis" ARG0: x3 ]  [ '
        '_can_v_modal<5:8> LBL: h1 ARG0: e2 ARG1: h9 ]  [ _read_v_1<9:13> LBL: h10 ARG0: e11 [ e SF: prop TENSE: untensed '
        'MOOD: indicative PROG: - PERF: - ] ARG1: x3 ARG2: x12 [ x PERS: 3 NUM: sg ] ]  [ _the_q<14:17> LBL: h13 ARG0: '
        'x12 RSTR: h14 BODY: h15 ]  [ compound<18:31> LBL: h16 ARG0: e17 [ e SF: prop TENSE: untensed MOOD: indicative '
        'PROG: - PERF: - ] ARG1: x12 ARG2: x18 [ x PT: notpro ] ]  [ udef_q<18:25> LBL: h19 ARG0: x18 RSTR: h20 BODY: h21 '
        ']  [ _finance_n_1<18:25> LBL: h22 ARG0: x18 ]  [ _data_n_1<26:31> LBL: h16 ARG0: x12 ] > HCONS: < h0 qeq h1 h5 '
        'qeq h7 h9 qeq h10 h14 qeq h16 h20 qeq h22 > ICONS: < > ]',
    'Luis never approved the request.':
        '[ LTOP: h0 INDEX: e2 [ e SF: prop TENSE: past MOOD: indicative PROG: - PERF: - ] RELS: < [ proper_q<0:4> LBL: h4 '
        'ARG0: x3 [ x PERS: 3 NUM: sg IND: + ] RSTR: h5 BODY: h6 ]  [ named<0:4> LBL: h7 CARG: "Luis" ARG0: x3 ]  [ '
        '_never_a_1<5:10> LBL: h1 ARG0: i9 ARG1: h10 ]  [ _approve_v_1<11:19> LBL: h11 ARG0: e2 ARG1: x3 ARG2: x12 [ x '
        'PERS: 3 NUM: sg IND: + ] ]  [ _the_q<20:23> LBL: h13 ARG0: x12 RSTR: h14 BODY: h15 ]  [ _request_n_for<24:32> '
        'LBL: h16 ARG0: x12 ARG1: i17 ] > HCONS: < h0 qeq h1 h5 qeq h7 h10 qeq h11 h14 qeq h16 > ICONS: < > ]',
    'Unless Jordan approves it, the release waits.':
        '[ LTOP: h0 INDEX: e2 [ e SF: prop TENSE: pres MOOD: indicative PROG: - PERF: - ] RELS: < [ _unless_p_1<0:6> LBL: '
        'h1 ARG0: e4 [ e SF: prop TENSE: untensed MOOD: indicative PROG: - PERF: - ] ARG1: h5 ARG2: h6 ]  [ '
        'proper_q<7:13> LBL: h7 ARG0: x8 [ x PERS: 3 NUM: sg IND: + ] RSTR: h9 BODY: h10 ]  [ named<7:13> LBL: h11 CARG: '
        '"Jordan" ARG0: x8 ]  [ _approve_v_1<14:22> LBL: h13 ARG0: e14 [ e SF: prop TENSE: pres MOOD: indicative PROG: - '
        'PERF: - ] ARG1: x8 ARG2: x15 [ x PERS: 3 NUM: sg GEND: n PT: std ] ]  [ pron<23:26> LBL: h16 ARG0: x15 ]  [ '
        'pronoun_q<23:26> LBL: h17 ARG0: x15 RSTR: h18 BODY: h19 ]  [ _the_q<27:30> LBL: h20 ARG0: x3 [ x PERS: 3 NUM: sg '
        '] RSTR: h21 BODY: h22 ]  [ _release_n_of<31:38> LBL: h23 ARG0: x3 ARG1: i24 ]  [ _wait_v_1<39:45> LBL: h25 ARG0: '
        'e2 ARG1: x3 ARG2: i26 ] > HCONS: < h0 qeq h1 h5 qeq h25 h6 qeq h13 h9 qeq h11 h18 qeq h16 h21 qeq h23 > ICONS: < '
        '> ]',
    'When did Jordan remove Luis?':
        '[ LTOP: h0 INDEX: e2 [ e SF: ques TENSE: past MOOD: indicative PROG: - PERF: - ] RELS: < [ loc_nonsp<0:4> LBL: '
        'h1 ARG0: e4 [ e SF: prop TENSE: untensed MOOD: indicative PROG: - PERF: - ] ARG1: e2 ARG2: x5 [ x PERS: 3 NUM: '
        'sg ] ]  [ time_n<0:4> LBL: h6 ARG0: x5 ]  [ which_q<0:4> LBL: h7 ARG0: x5 RSTR: h8 BODY: h9 ]  [ proper_q<9:15> '
        'LBL: h10 ARG0: x3 [ x PERS: 3 NUM: sg IND: + ] RSTR: h11 BODY: h12 ]  [ named<9:15> LBL: h13 CARG: "Jordan" '
        'ARG0: x3 ]  [ _remove_v_1<16:22> LBL: h1 ARG0: e2 ARG1: x3 ARG2: x15 [ x PERS: 3 NUM: sg IND: + ] ]  [ '
        'proper_q<23:28> LBL: h16 ARG0: x15 RSTR: h17 BODY: h18 ]  [ named<23:28> LBL: h19 CARG: "Luis" ARG0: x15 ] > '
        'HCONS: < h0 qeq h1 h8 qeq h6 h11 qeq h13 h17 qeq h19 > ICONS: < > ]',
    'When the token expires, the session ends.':
        '[ LTOP: h0 INDEX: e2 [ e SF: prop TENSE: pres MOOD: indicative PROG: - PERF: - ] RELS: < [ _when_x_subord<0:4> '
        'LBL: h1 ARG0: e4 [ e SF: prop TENSE: untensed MOOD: indicative PROG: - PERF: - ] ARG1: h5 ARG2: h6 ]  [ '
        '_the_q<5:8> LBL: h7 ARG0: x8 [ x PERS: 3 NUM: sg IND: + ] RSTR: h9 BODY: h10 ]  [ _token_n_1<9:14> LBL: h11 '
        'ARG0: x8 ]  [ _expire_v_1<15:23> LBL: h12 ARG0: e13 [ e SF: prop TENSE: pres MOOD: indicative PROG: - PERF: - ] '
        'ARG1: x8 ]  [ _the_q<24:27> LBL: h14 ARG0: x3 [ x PERS: 3 NUM: sg IND: + ] RSTR: h15 BODY: h16 ]  [ '
        '_session_n_1<28:35> LBL: h17 ARG0: x3 ]  [ _end_v_1<36:41> LBL: h18 ARG0: e2 ARG1: x3 ] > HCONS: < h0 qeq h1 h5 '
        'qeq h18 h6 qeq h12 h9 qeq h11 h15 qeq h17 > ICONS: < > ]',
}


def said(sentence):
    """What the bridge says of a sentence ACE read: its meaning, or None with the gaps that keep it from being
    said."""
    return em.meaning_of(eds.from_mrs(simplemrs.decode(READ[sentence])))


def facts(sentence):
    """Each fact as (relation, subject, obj, not-so, a condition, not told as so)."""
    meaning = said(sentence).meaning
    assert meaning is not None, sentence
    return {(f.relation, f.subject, f.obj, not f.positive, f.condition, f.unasserted) for f in meaning.facts}


def about(sentence, relation):
    return {f for f in facts(sentence) if f[0] == relation}


def test_a_happening_denied_is_said_not_to_have_happened():
    """"Jordan did not disable Luis's account.": the disabling is denied, by the fact Lyric's own reading writes for
    it (`grammar.spell_out`), and its places are not -- Jordan still did whatever was not done."""
    held = facts("Jordan did not disable Luis's account.")
    assert ("has_property", "?v2", "false", False, False, False) in held
    assert ("done_by", "?v2", "jordan", False, False, False) in held
    assert not any(f[3] for f in held), "nothing is marked not so; the denial is the happening's own fact"


def test_never_denies_the_happening_as_not_does():
    """"Luis never approved the request.": one word, the same denial. Read as a quality, this said the approving
    happened and was `has_property(?v, never)` besides."""
    held = facts("Luis never approved the request.")
    assert ("has_property", "?v2", "false", False, False, False) in held
    assert not any(f[2] == "never" for f in held)


def test_a_denial_reaches_through_a_hedge_to_what_a_thing_is_not():
    """"Jordan might not be an administrator.": the denial stands over the modal, which stands over the being, and
    what it finally denies is the one fact there is -- that Jordan is an administrator. A copula is no happening, so
    there is nothing to say did not happen and the fact itself is not so (`MeaningFact.positive`)."""
    held = facts("Jordan might not be an administrator.")
    assert ("instance_of", "jordan", "administrator", True, False, True) in held
    assert not any(f[2] == "false" for f in held), "no happening was denied; there is no happening"


def test_a_hedged_happening_is_not_told_as_so_and_its_status_is():
    """"Jordan may have disabled Luis's account.": that it happened is not told (`unasserted`), that it is possible
    is. Read as an ordinary predicate this was a happening named "may" with the disabling told as fact, and nothing
    was named as a gap, so the loss was silent."""
    held = facts("Jordan may have disabled Luis's account.")
    assert ("instance_of", "?v2", "disable", False, False, True) in held
    assert ("done_by", "?v2", "jordan", False, False, True) in held
    assert ("has_property", "?v2", "possible", False, False, False) in held
    assert not any(f[2] == "may" for f in held)


def test_what_have_done_says_of_when_survives_a_hedge():
    """"may have disabled": the ERG holds the perfect apart from the tense and leaves the happening under a modal
    untensed, so read by tense alone a hedged happening lost its time altogether."""
    assert ("precedes", "?v2", "?now", False, False, True) in facts("Jordan may have disabled Luis's account.")


def test_a_condition_holds_its_own_clause_and_not_the_other():
    """"If Jordan disables the account, Luis loses his access.": the disabling is the condition, the losing is told.
    Left unread, `_if_x_then` was a gap by name and the whole sentence was said as nothing."""
    held = facts("If Jordan disables the account, Luis loses his access.")
    conditional = {f for f in held if f[4]}
    assert ("instance_of", "?v2", "disable", False, True, False) in conditional
    assert ("done_by", "?v2", "jordan", False, True, False) in conditional
    assert ("instance_of", "?v5", "lose", False, False, False) in held
    assert not any(f[1] == "?v5" and f[4] for f in held), "the consequent is told, not conditional"


def test_when_something_happens_is_a_condition_too():
    """"When the token expires, the session ends.": the ERG gives every subordinator the same two places, so one
    rule reads `_when_x_subord` as it reads `_if_x_then`."""
    held = facts("When the token expires, the session ends.")
    assert ("instance_of", "?v2", "expire", False, True, False) in held
    assert ("instance_of", "?v4", "end", False, False, False) in held


def test_unless_is_the_condition_denied():
    """"Unless Jordan approves it, the release waits.": the waiting holds where the approving does NOT, which is how
    Lyric's own reading says it (`propbank_roles`: "unless" a condition with `positive` False)."""
    held = facts("Unless Jordan approves it, the release waits.")
    assert ("instance_of", "?v2", "approve", True, True, False) in held
    assert ("done_by", "?v2", "jordan", True, True, False) in held
    assert ("instance_of", "?v5", "wait", False, False, False) in held


def test_a_phrase_filling_a_verbs_place_is_nobody_who_took_part():
    """"Jordan removed Luis from the finance team.": the ERG numbers the "from" phrase among the verb's places
    (`ARG3`), and read as a third participant every such sentence said somebody received something, of a term no
    other fact mentioned. What the phrase says is the preposition's to say: Luis came from the team."""
    held = facts("Jordan removed Luis from the finance team.")
    assert not about("Jordan removed Luis from the finance team.", "received_by")
    assert ("done_to", "?v1", "luis", False, False, False) in held
    assert ("moves_from", "luis", "?v6", False, False, False) in held


def test_a_place_really_filled_is_still_read():
    """"Jordan gave Luis the admin role.": the rule above must not cost a real third place -- Luis received it."""
    assert ("received_by", "?v1", "luis", False, False, False) in facts("Jordan gave Luis the admin role.")


def test_a_time_asked_is_when_and_not_where():
    """"When did Jordan remove Luis?": the ERG says a bare time with the predicate it says a bare place with
    (`loc_nonsp`), and what tells them apart is what fills its second place."""
    held = facts("When did Jordan remove Luis?")
    assert ("during", "?v3", "?v1", False, False, False) in held
    assert not any(f[0] == "located_in" for f in held)
    assert said("When did Jordan remove Luis?").meaning.asked == ("?v1",)


def test_what_someone_can_do_is_an_ability_and_not_a_doing():
    """"Luis can read the finance data.": no reading ever happened, so the reading is not told as so and what is
    told is the ability (`relation_types.CAPABLE_OF`)."""
    held = facts("Luis can read the finance data.")
    assert ("capable_of", "luis", "read", False, False, False) in held
    assert ("instance_of", "?v2", "read", False, False, True) in held
    assert not any(f[2] == "can" for f in held)


def test_obligation_is_a_gap_by_name_and_not_a_happening_called_must():
    """"Jordan must approve the request.": the meaning language has no words for obligation, so the sentence is said
    as nothing and the reason is named -- never read as a happening named "must"."""
    answer = said("Jordan must approve the request.")
    assert answer.meaning is None
    assert answer.gaps == ("nothing said for:_must_v_modal",)


@pytest.mark.parametrize("sentence", sorted(READ))
def test_every_sentence_read_is_said_or_names_why_not(sentence):
    """Nothing comes back half said: a meaning, or None with the gaps that keep it from being said."""
    answer = said(sentence)
    assert (answer.meaning is None) == bool(answer.gaps)
