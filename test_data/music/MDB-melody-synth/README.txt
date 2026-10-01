MDB-melody-synth
================

MDB-melody-synth (c) by Justin Salamon, Rachel Bittner, Jordi Bonada, Juan Jose Bosch, Emilia Gómez and Juan Pablo Bello.
MDB-melody-synth is licensed under the Creative Commons Attribution-NonCommercial 4.0 International License (CC BY-NC 4.0). 
You should have received a copy of the license along with this work. If not, see http://creativecommons.org/licenses/by-nc/4.0/


Created By
----------

Justin Salamon*, Rachel Bittner*, Jordi Bonada^, Juan Jose Bosch^, Emilia Gómez^ and Juan Pablo Bello*.
* Music and Audio Research Lab (MARL), New York University, USA
^ Music Technology Group, Universitat Pompeu Fabra, Spain
http://synthdatasets.weebly.com/
http://steinhardt.nyu.edu/marl/
https://www.upf.edu/web/mtg

Version 1.0.0


Description
-----------

MDB-melody-synth contains 65 songs from the MedleyDB dataset (http://medleydb.weebly.com/) in which the melody track 
has been resynthesized to obtain a perfect melody f0 annotation using the analysis/synthesis method described in the 
following publication:

J. Salamon, R. M. Bittner, J. Bonada, J. J. Bosch, E. Gómez, and J. P. Bello. "An analysis/synthesis framework for 
automatic f0 annotation of multitrack datasets". In 18th Int. Soc. for Music Info. Retrieval Conf., Suzhou, China, 
Oct. 2017.

This dataset includes:
* 65 stereo wav files of song mixes where the original melody stem (track) has been replaced with a resynthesized one
* 65 mono wav files containing the resynthesized melody stem (track) only
* 65 csv files containing a perfect f0 annotation of the melody stem (track) obtained via the analysis/synthesis 
  method described in the paper

The data come in three folders, the contents of which is described below.


audio_mix
---------
Contains 65 stereo wav files of song mixes where the original melody stem (track) has been replaced with a 
resynthesized one. All other stems (tracks) in the mix are the original ones (not resynthesized). The resynthesized  
melody is obtained via the analysis/synthesis method described in the paper, and is automatically mixed together 
with the rest of the stems as described in the paper.

Naming convention: 
<artist>_<songtitle>_MIX_melsynth.wav

Example: 
AClassicEducation_NightOwl_MIX_melsynth.wav


audio_melody
------------
Contains 65 mono wav files of the resynthesized melody stem (track) only. The resynthesized melody is obtained via the 
analysis/synthesis method described in the paper.

Naming convention: 
<artist>_<songtitle>_STEM_<stemID>.RESYN.wav

Example: 
AClassicEducation_NightOwl_STEM_08.RESYN.wav


annotation_melody
-----------------
Contains 65 csv files containing a perfect f0 annotation of the melody stem (track) obtained via the analysis/synthesis 
method described in the paper. 

Format:
Each file contains two comma-separated columns, the first containing timestamps and the second containing the melody 
f0 in Hz. The first frame in the annotation is zero-centered. Silence is indicated as 0 Hz. The hop size of the 
annotation is 128/44100 seconds (~2.9 ms).

Naming convention:
<artist>_<songtitle>_STEM_<stemID>.RESYN.csv

Example:
AClassicEducation_NightOwl_STEM_08.RESYN.csv


Please Acknowledge MDB-melody-synth in Academic Research
--------------------------------------------------------

Please cite the following publication when using MDB-melody-synth:

J. Salamon, R. M. Bittner, J. Bonada, J. J. Bosch, E. Gómez, and J. P. Bello. "An analysis/synthesis framework for 
automatic f0 annotation of multitrack datasets". In 18th Int. Soc. for Music Info. Retrieval Conf., Suzhou, China, 
Oct. 2017.

For information about the original MedleyDB dataset please see (and cite):

R. M. Bittner, J. Salamon, M. Tierney, M. Mauch, C. Cannam, and J. P. Bello. MedleyDB: A multitrack dataset for 
annotation-intensive MIR research. In 15th Int. Soc. for Music Info. Retrieval Conf., pages 155–160, Taipei, Taiwan, 
Oct. 2014.


Conditions of Use
-----------------

Dataset created by Justin Salamon, Rachel Bittner, Jordi Bonada, Juan Jose Bosch, Emilia Gómez and Juan Pablo Bello. 
 
The MDB-melody-synth dataset is offered free of charge under the terms of the Creative Commons
Attribution-NonCommercial 4.0 International License (CC BY-NC 4.0): http://creativecommons.org/licenses/by-nc/4.0/
 
The dataset and its contents are made available on an "as is" basis and without warranties of any kind, including 
without limitation satisfactory quality and conformity, merchantability, fitness for a particular purpose, accuracy or 
completeness, or absence of errors. Subject to any liability that may not be excluded or limited by law, NYU is not 
liable for, and expressly excludes, all liability for loss or damage however and whenever caused to anyone by any use of 
the MDB-melody-synth dataset or any part of it.


Feedback
--------

Please help us improve MDB-melody-synth by sending your feedback to: justin.salamon@gmail.com
In case of a problem report please include as many details as possible.
