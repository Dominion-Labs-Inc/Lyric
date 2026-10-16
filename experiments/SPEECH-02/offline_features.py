"""SPEECH-02, offline: which of a few classical, model-free ways of measuring a word carries across speakers.

No store and no substrate. The clips `offline_naming.py` presented (10 speakers a word to teach, 3 untaught to
hear), measured each way below, and scored as that study scores: the word whose nearest example is nearest, and the
right word among the nearest five, with 3, 5 and 10 teaching speakers.
  ear       the ear as it is (`speech.word_features`): cepstra less their mean, their change, formants
  cmvn      cepstra less their mean AND over their spread, over the word (Viikki and Laurila 1998), their change,
            formants
  cmvn+dd   cmvn with the change of the change
  cep       cmvn cepstra and their change, no formants
  lifter    the ear's cepstra lifted (Juang, Rabiner and Wilpon 1987), their change, formants

    ./venv_lyric/bin/python3 experiments/SPEECH-02/offline_features.py
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))


def main() -> int:
    import numpy as np
    from core.perception import hearing as H
    from core.perception import speech as SP
    work = HERE / "work" / "offline"
    taught = {}
    for path in sorted((work / "teach").glob("*/*.wav")):
        taught.setdefault(path.parent.name, []).append(path)
    heard = [(path.parent.name, path) for path in sorted((work / "heard").glob("*/*.wav"))]
    lifter = 1 + (22 / 2) * np.sin(np.pi * np.arange(1, SP._CEPSTRA + 1) / 22)

    def measured(path, how):
        y = np.asarray(H.decode(str(path)), dtype=np.float64)
        lo, hi, _ = SP._extent(y)
        cep = SP._cepstrum(y)[0][lo:hi]
        if len(cep) < 3:
            return np.zeros((0, 2))
        if how == "ear":
            return SP._measure(y, SP._cepstrum(y)[0], lo, hi)
        if how == "lifter":
            cep = (cep - cep.mean(axis=0)) * lifter
        else:
            cep = (cep - cep.mean(axis=0)) / (cep.std(axis=0) + 1e-6)
        parts = [cep, np.gradient(cep, axis=0)]
        if how == "cmvn+dd":
            parts.append(np.gradient(parts[1], axis=0))
        if how != "cep":
            parts.append(SP._formants(y[lo * SP._HOP:hi * SP._HOP], len(cep)))
        return np.concatenate(parts, axis=1)

    report = {}
    for how in ("ear", "cmvn", "cmvn+dd", "cep", "lifter"):
        started = time.time()
        examples = {w: [measured(p, how) for p in paths] for w, paths in taught.items()}
        tests = [(w, measured(p, how)) for w, p in heard]
        distance = [{w: [SP.warp(f, e) for e in ex] for w, ex in examples.items()} for _, f in tests]
        row = {}
        for k in (3, 5, 10):
            near = top5 = 0
            for (said, _), d in zip(tests, distance):
                per = {w: min(ds[:k]) for w, ds in d.items()}
                order = sorted(per, key=per.get)
                near += order[0] == said
                top5 += said in order[:5]
            row[k] = (round(100 * near / len(tests), 1), round(100 * top5 / len(tests), 1))
        report[how] = row
        print(f"  {how:8s} nearest / in nearest five, with 3, 5, 10 speakers: "
              + "  ".join(f"{k}: {a}% / {b}%" for k, (a, b) in row.items()) + f"  ({time.time() - started:.0f} s)",
              flush=True)
    (HERE / "work" / "offline_features.json").write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
