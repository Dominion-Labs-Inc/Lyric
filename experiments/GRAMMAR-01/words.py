"""What GRAMMAR-01 holds of each word, from files, standing in for memory, read the way main reads it.

How each word is used is counted by `grammar_words.HeldWords` from UD English EWT's training part as Lyric reads a
treebank (`teaching_sources.read_conllu`: the sentences main holds analysed), and the forms each word is written in
(`word_forms`, as main holds them: "came" the past of `come`); what each word's thing is comes from
`grammar_words.GraphKnowledge` holding WordNet's links as `WordNetSource` teaches them (`isa`, `instance_of`,
`defined_with`: the records main was taught); a word is named by WordNet's plain form (`morphy`), else as the
treebank's lemmas have it, where main asks memory (`MemoryAgent.name_of`).

WordNet's links are kept beside the treebank (`grammar_wordnet_links.pkl`, never pushed) once read: about a minute."""
from core.learning.teaching_sources import file_structure, file_words  # noqa: F401  (moved to core)
