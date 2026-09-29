"""Lyric's core: the substrate.

Importing the package imports nothing else. Each part is imported where it is
used, from its own module, so importing one part never pulls in the rest: a
sense's own process loads the describers alone, not the coordinator.
"""
