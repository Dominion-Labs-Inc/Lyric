# SONGS-01: music heard by the substrate

**Finding (2026-09-29).** The substrate hears music with no model (`core/perception/music.py`).
- Songs are taught by hearing them, and known again through a real room and a codec.
- A song's key and tempo are heard as people annotated them.
- A sung melody is heard as its notes, remembered in words, and recalled as the same notes.
- Speech is heard as no music.
- A song taught by one person humming it is known when another person hums it, in their own key and pace
  (`has_tune_of`), and a hum of a song never taught is not named.

**Fourth run: 25/25** (record `20260929T233853Z`; cleanup by nonce, 1,091 rows written, 0 left). New section J
(HumTrans VALID, one segment of each of three songs taught from F01's hum): the lesson's trace keeps the tune
(255 points); F02 humming the first song has its tune (ratio 0.325, support 1.0), its memory says 'the tune of
"…"', the graph and the beliefs hold `has_tune_of`, and F02 humming a song never taught has no song's tune. The
measure behind it is TUNES-01.

**Third run: 20/20** (record `20260929T131355Z`; cleanup by nonce, 875 rows written, 0 left). The two
defects the first run found are fixed at the root, and the second run (19/20) found where the second fix was
incomplete:
- the landmark floor counts distinct landmarks;
- a producer can say a label is a NAME (`is_name`), and a name keeps its words (`canonical_label(name=True)`);
  prose is read exactly as before. The second run still put `in_key a_major` on `major`: the recording's edge
  was recorded before the key's own concept existed, and fell back to the word. A target the same evidence
  declares a name is now resolved only as that name, or left waiting for it. Reviewed by the session that owns
  the language layer; identity tests 47/47 there.

**First run: 17/20** (record `20260929T123554Z`). The three failures came from two real defects, and neither is
adjusted away here:
- **A plain tone was taught as a song.** A 1-second 440 Hz tone read from a file gave 107 landmarks, over the floor of
  100, but only 66 different ones, and any other 440 Hz tone agrees with them. That failed two checks: the refusal, and
  the taught songs read back after a restart. **Fixed:** the floor now counts distinct landmarks (`hearing.distinct_landmarks`),
  for songs and known sounds alike. HEAR-01's references are unchanged by it: Glass keeps 270, Tink 6.
- **"A major" lost its tonic in the graph.** The belief reads `in_key a_major`; the graph concept is `major`. The
  shared identity rule (`lexical_normalization.canonical_term`) strips a leading a/an/the and singularises every label.
  That is right for prose and wrong for names: "A Day in the Life" becomes `day_in_the_life` and "The Beatles"
  becomes `beatle`. **Fixed** (see the third run).

**What held, in the first run:**

| | measured |
|---|---|
| each taught song known from 6 s of it played into a real room, 64 kbit/s | 3 of 3, support 1.0 |
| a song never taught known as a taught one | 0 |
| key of country.00013 (annotated A major) | A major, support 0.95 |
| tempo of country.00013 (annotated 127.05 bpm) | 127.0 bpm |
| sung notes against the annotator (onset 50 ms, pitch 50 cents) | 0.734 over 81 notes |
| the melody rebuilt from its trace, against the melody heard | 0.852 |
| key, tempo, melody or song claimed of JFK's speech | none |
| a clip whose sound track is a taught song | heard playing it |

**Measured before the build** (scratch measurements; the numbers are in `music.py` beside the constants they set):
- key: GTZAN 837 clips, exact 52.7%, weighted 0.629. GiantSteps 225 single-key tracks, held out: exact 59.1%, weighted
  0.679. Claimed keys (fit at least 0.82) are right about 80% on both.
- tempo: GTZAN 998 clips, within 4% on 63.7%, 89.1% counting half and double speed; beats F 0.769 at 70 ms.
- notes: vocadito, 40 solo singers, onset and pitch F 0.70 against annotator 1. The two annotators agree at 0.74.
- melody claimed: 37 of 40 sung recordings, 2 of 600 LibriSpeech utterances.
- songs known: 100 GTZAN clips taught, 6 s excerpts in the room and codec. The share of landmarks agreeing with their
  own song was 0.30 at the least; no excerpt of 300 others reached 0.029 with any taught song.

**Properties checked:** A taught (4), B restart (2), C known (3), D key and tempo (2), E admitted (3), F melody (3),
G recalled (1), H speech (1), I video (1).

**Recordings:** GTZAN (keys: Kraft and Lerch; tempo: GTZAN-Rhythm), vocadito (CC BY 4.0), JFK's inaugural sample, a
real room recorded from this Mac's microphone (LIVE-01), and the repo's jellyfish footage.

Run (sandbox store): `./venv_lyric/bin/python3 experiments/SONGS-01/experiment.py`
