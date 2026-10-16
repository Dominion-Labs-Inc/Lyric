"""The ear's sense of which sounds were said: a trained phone recogniser, and nothing more.

Model-free hearing tells English sounds apart about half the time (SPEECH-02 to -04), too seldom to follow a
sentence. This reports, every 20 ms, how much each of 39 English sounds was said, or nothing new (its blank). It
holds no words and no language model: which words were said, what they mean, and which was meant are Lyric's
(`speech.find_words_by_marks`, the pronunciations taught as memory, the listener). On 2026-10-03 the teammate who
held the session read model-free as no LLM and nothing that takes intelligence away from Lyric; a sense that only
reports sounds is within that. The owner declined added learned parameters on 2026-09-30, so this is behind
`LYRIC_SPEECH` and its own `LYRIC_EAR` ("recogniser" or "off").

The recogniser: `vitouphy/wav2vec2-xls-r-300m-timit-phoneme` (Apache-2.0; wav2vec2 XLS-R fine-tuned on TIMIT's phones;
315 million parameters), loaded once in hearing's process, on the Mac's GPU where there is one. Measured offline
(SPEECH-05): of words said in untaught speakers' sentences, 89.0% fit best among about 1,000; whole sentences, 78.2%
of words right with no word boundary given.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

import numpy as np

MODEL = "vitouphy/wav2vec2-xls-r-300m-timit-phoneme"
#: The recogniser's frames, in seconds.
STEP = 0.02
#: Its sounds, written as the CMU Pronouncing Dictionary writes them. TIMIT's 39 join "ɔ" with "ɑ" and "ʒ" with "ʃ",
#: so AO and ZH take those; its flap "ɾ" is a T or a D.
AS_CMU: Dict[str, List[str]] = {
    "AA": ["ɑ"], "AO": ["ɑ"], "AE": ["æ"], "AH": ["ə"], "AW": ["aʊ"], "AY": ["aɪ"], "B": ["b"], "CH": ["ʧ"],
    "D": ["d", "ɾ"], "DH": ["ð"], "EH": ["ɛ"], "ER": ["ɝ"], "EY": ["eɪ"], "F": ["f"], "G": ["g"], "HH": ["h"],
    "IH": ["ɪ"], "IY": ["i"], "JH": ["ʤ"], "K": ["k"], "L": ["l"], "M": ["m"], "N": ["n"], "NG": ["ŋ"],
    "OW": ["oʊ"], "OY": ["ɔɪ"], "P": ["p"], "R": ["ɹ"], "S": ["s"], "SH": ["ʃ"], "T": ["t", "ɾ"], "TH": ["θ"],
    "UH": ["ʊ"], "UW": ["u"], "V": ["v"], "W": ["w"], "Y": ["j"], "Z": ["z"], "ZH": ["ʃ"],
}
#: A recording is heard in pieces of at most this many seconds, each with this much heard around it, so a long sound
#: track is heard whole without holding it all at once.
PIECE = 30.0
AROUND = 1.0
#: The phones in the order the marks are columns, and the blank last.
PHONES: List[str] = sorted(AS_CMU)
INDEX: Dict[str, int] = {p: i for i, p in enumerate(PHONES)}
BLANK = len(PHONES)


def wanted() -> bool:
    """Whether the ear may use the recogniser (`LYRIC_EAR`, "recogniser" unless "off")."""
    return os.environ.get("LYRIC_EAR", "recogniser").strip().lower() not in ("off", "0", "no", "false")


class PhoneRecogniser:
    """Loaded once, on first use."""

    def __init__(self):
        import torch
        from transformers import AutoModelForCTC, AutoProcessor
        from transformers.utils import logging as loading
        loading.disable_progress_bar()
        self._torch = torch
        from huggingface_hub import snapshot_download
        # LOADED FROM THIS MACHINE ONLY: hearing never reaches the network. It is put once in the model cache the
        # substrate's settings name (`HF_HOME`), by `huggingface-cli download` of `MODEL` with that `HF_HOME`. It is
        # loaded from its folder there: given the name, `AutoProcessor` asks huggingface.co for a file the model does
        # not have even with `local_files_only`.
        folder = snapshot_download(MODEL, local_files_only=True)
        self.processor = AutoProcessor.from_pretrained(folder)
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.model = AutoModelForCTC.from_pretrained(folder).to(self.device).eval()
        vocab = self.processor.tokenizer.get_vocab()
        columns = np.zeros((self.model.config.vocab_size, len(PHONES) + 1), dtype=np.float32)
        for phone, sounds in AS_CMU.items():
            for sound in sounds:
                columns[vocab[sound], INDEX[phone]] = 1.0
        for token in ("[PAD]", " ", "|"):
            if token in vocab:
                columns[vocab[token], BLANK] = 1.0
        self._columns = columns

    def marks(self, y: np.ndarray, rate: int) -> np.ndarray:
        """How much each phone, and nothing new, was said every 20 ms of `y` (sampled at `rate`), as logs."""
        from scipy.signal import resample_poly
        y16 = resample_poly(np.asarray(y, dtype=np.float64), 16000, rate).astype(np.float32)
        if len(y16) < 400:
            return np.zeros((0, len(PHONES) + 1), dtype=np.float32)
        piece, around, step = int(PIECE * 16000), int(AROUND * 16000), int(STEP * 16000)
        out = []
        for start in range(0, len(y16), piece):
            a = max(start - around, 0)
            heard = self._heard(y16[a:min(start + piece + around, len(y16))])
            skip = int(round((start - a) / step))
            out.append(heard[skip:skip + int(np.ceil((min(start + piece, len(y16)) - start) / step))])
        return np.concatenate(out)

    def _heard(self, y16: np.ndarray) -> np.ndarray:
        torch = self._torch
        inputs = self.processor(y16, sampling_rate=16000, return_tensors="pt").input_values.to(self.device)
        with torch.no_grad():
            probs = torch.softmax(self.model(inputs).logits[0], dim=-1).float().cpu().numpy()
        return np.log(probs @ self._columns + 1e-8).astype(np.float32)


_LOADED: Optional[PhoneRecogniser] = None


def recogniser() -> Optional[PhoneRecogniser]:
    """The recogniser, loaded on first use; None when the ear may not use one (`wanted`). A recogniser that cannot be
    loaded raises: it is never quietly taken as none."""
    global _LOADED
    if not wanted():
        return None
    if _LOADED is None:
        _LOADED = PhoneRecogniser()
    return _LOADED
