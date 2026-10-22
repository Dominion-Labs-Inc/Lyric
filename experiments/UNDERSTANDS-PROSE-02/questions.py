"""The questions of UNDERSTANDS-PROSE-02, written from each text before any of it was read by the substrate.

A yes or no question is answered "yes" or "no"; a question asking what, who, when or how many is answered by any of
the words listed, looked for in the reply. A "no" is asked only where the text says otherwise. Questions about what
follows join two things the text says (Sri Lanka is in South Asia, South Asia is in Asia)."""

Q = {}

Q["South Asia"] = [
    ("Is South Asia a sub-region of Asia?", "yes"),
    ("What is the population of South Asia?", ["2.04"]),
    ("Is Bhutan a state of South Asia?", "yes"),
    ("Is Sri Lanka in Asia?", "yes"),
    ("What does South Asia border to the northeast?", ["East Asia"]),
    ("What bounds South Asia in the south?", ["Indian Ocean"]),
    ("Which mountains bound South Asia in the north?", ["Himalaya", "Karakoram", "Pamir"]),
    ("What did settled life on the Indian subcontinent evolve into?", ["Indus Valley"]),
    ("Is Sanskrit an Indo-European language?", "yes"),
    ("How many atolls does the Maldives have?", ["26"]),
]

Q["Military"] = [
    ("What is a military primarily intended for?", ["warfare", "war"]),
    ("What is a military also known as?", ["armed forces"]),
    ("Who typically authorizes and maintains militaries?", ["state"]),
    ("Can a military include a navy?", "yes"),
    ("Is a navy a military branch?", "yes"),
    ("What is the main task of a military?", ["defence", "defense", "defend"]),
    ("Is the profession of soldiering older than recorded history?", "yes"),
    ("When was the Battle of Kadesh?", ["1274"]),
    ("From whose reign was the Battle of Kadesh?", ["Ramses"]),
    ("Are the members of a military identifiable by a uniform?", "yes"),
]

Q["The Beatles"] = [
    ("Where were the Beatles formed?", ["Liverpool"]),
    ("When were the Beatles formed?", ["1960"]),
    ("Was Ringo Starr a member of the Beatles?", "yes"),
    ("Were the Beatles an English band?", "yes"),
    ("What was Lennon's previous group?", ["Quarrymen"]),
    ("When did Starr join the Beatles?", ["1962"]),
    ("Who was the Beatles' manager?", ["Epstein"]),
    ("What was the Beatles' first hit?", ["Love Me Do"]),
    ("What nickname did the band acquire?", ["Fab Four"]),
    ("Did the Beatles play clubs in Hamburg?", "yes"),
]

Q["Africa"] = [
    ("Is Africa a continent?", "yes"),
    ("Which continent is larger than Africa?", ["Asia"]),
    ("What was the median age in Africa in 2012?", ["19.7"]),
    ("What will Africa's population exceed by 2100?", ["3.8"]),
    ("Does Africa straddle the equator?", "yes"),
    ("Which ocean is to the west of Africa?", ["Atlantic"]),
    ("Which sea is to the north of Africa?", ["Mediterranean"]),
    ("Is Africa the least wealthy inhabited continent per capita?", "yes"),
    ("Which continent is Africa ahead of in total wealth?", ["Oceania"]),
    ("Does Spain have territory on African soil?", "yes"),
]

Q["Microeconomics"] = [
    ("Is microeconomics a branch of economics?", "yes"),
    ("Whose behavior does microeconomics study?", ["individual", "firm"]),
    ("Which field studies the economy as a whole?", ["macroeconomics"]),
    ("What does macroeconomics focus on?", ["economic activity", "growth", "inflation", "unemployment"]),
    ("Does microeconomics analyze market failure?", "yes"),
    ("In market failure, what do markets fail to produce?", ["efficient"]),
    ("Does macroeconomics address inflation?", "yes"),
    ("What is much of modern macroeconomic theory built upon?", ["microfoundations"]),
]

Q["Iron"] = [
    ("Is iron a chemical element?", "yes"),
    ("Is Fe the symbol of iron?", "yes"),
    ("What is the atomic number of iron?", ["26"]),
    ("Is iron a metal?", "yes"),
    ("What is the most common element on Earth by mass?", ["iron"]),
    ("Is iron the fourth most abundant element in the Earth's crust?", "yes"),
    ("What was metallic iron mainly deposited by?", ["meteorite"]),
    ("Is steel an iron alloy?", "yes"),
    ("What is the cheapest metal?", ["iron"]),
    ("What did the use of iron tools and weapons displace?", ["copper"]),
]

Q["Gas"] = [
    ("Is gas a state of matter?", "yes"),
    ("Does gas have a fixed shape?", "no"),
    ("Is gas a compressible form of fluid?", "yes"),
    ("Is neon a noble gas?", "yes"),
    ("What distinguishes gases from liquids and solids?", ["separation"]),
    ("Can some gases be invisible to the human observer?", "yes"),
    ("Which state provides the upper-temperature boundary for gases?", ["plasma"]),
    ("What are super-cooled high-density atomic gases classified as?", ["Bose", "Fermi"]),
    ("Can pure gases be mixed together?", "yes"),
]

Q["Rain"] = [
    ("Is rain a form of precipitation?", "yes"),
    ("What is rain composed of?", ["droplet", "water"]),
    ("What is a brief, moderate rainfall called?", ["shower"]),
    ("What is a prolonged heavy rainfall called?", ["downpour"]),
    ("Is rain a component of the water cycle?", "yes"),
    ("Does rain provide water for crop irrigation?", "yes"),
    ("What is the major cause of rain production?", ["moisture", "weather front"]),
    ("What are cumulonimbus clouds also called?", ["thunder cloud"]),
    ("On which side of mountains can desert climates exist?", ["leeward"]),
    ("What brings rainy seasons to savannah climes?", ["monsoon", "Intertropical Convergence Zone"]),
]

Q["Reproduction"] = [
    ("Is reproduction a biological process?", "yes"),
    ("What is another word for reproduction?", ["procreation", "breeding"]),
    ("How many forms of reproduction are there?", ["two", "2"]),
    ("In asexual reproduction, can an organism reproduce without another organism?", "yes"),
    ("Is asexual reproduction limited to single-celled organisms?", "no"),
    ("Is cloning a form of asexual reproduction?", "yes"),
    ("What are gametes?", ["reproductive"]),
    ("What creates gametes?", ["meiosis"]),
    ("What does a sperm cell fertilize?", ["egg"]),
    ("What percentage of their genes do organisms pass on in sexual reproduction?", ["50"]),
]

Q["Earthquake"] = [
    ("What is an earthquake also called?", ["tremor", "temblor"]),
    ("Is an earthquake the shaking of the Earth's surface?", "yes"),
    ("What does the sudden release of energy in the lithosphere create?", ["seismic wave"]),
    ("Can fracking induce earthquakes?", "yes"),
    ("What is the initial point of rupture called?", ["hypocenter", "focus"]),
    ("What is the ground level directly above the hypocenter called?", ["epicenter"]),
    ("What are earthquakes primarily caused by?", ["fault"]),
    ("Where was the 1976 Tangshan earthquake?", ["China"]),
    ("What was the magnitude of the Valdivia earthquake?", ["9.5"]),
    ("Was the Valdivia earthquake in Chile?", "yes"),
]

Q["Neolithic Revolution"] = [
    ("What is the Neolithic Revolution also known as?", ["Agricultural Revolution"]),
    ("Was the Neolithic Revolution a transition to agriculture?", "yes"),
    ("What did the new knowledge lead to?", ["domestication"]),
    ("When did the domestication of plants and animals start?", ["11,700", "Holocene"]),
    ("Did the Neolithic Revolution narrow the diversity of foods available?", "yes"),
    ("Did the Neolithic Revolution increase the quality of human nutrition?", "no"),
    ("What did the Neolithic Revolution transform the groups of hunter-gatherers into?", ["sedentary"]),
    ("Where were the sedentary societies based?", ["village", "town"]),
    ("What allowed the production of surplus food?", ["irrigation", "deforestation", "cultivation"]),
    ("What did settled communities permit humans to experiment with?", ["plant"]),
]

Q["Islamic Golden Age"] = [
    ("Was the Islamic Golden Age a period of cultural flourishing?", "yes"),
    ("When did the Islamic Golden Age begin?", ["8th", "786", "Harun"]),
    ("Where was the House of Wisdom?", ["Baghdad"]),
    ("Into which language did the scholars translate classical knowledge?", ["Arabic"]),
    ("Is Al-Azhar University one of the world's oldest universities?", "yes"),
    ("Was Cairo a major intellectual center for the Islamic world?", "yes"),
    ("What was Córdoba the capital of?", ["Al-Andalus"]),
    ("When was the Siege of Baghdad?", ["1258"]),
    ("What did the period end with?", ["collapse", "Mongol", "Siege"]),
    ("Who was Harun al-Rashid?", ["caliph"]),
]

Q["Achaemenid Empire"] = [
    ("Who founded the Achaemenid Empire?", ["Cyrus"]),
    ("When was the Achaemenid Empire founded?", ["550"]),
    ("Was the Achaemenid Empire the largest empire of its time?", "yes"),
    ("Where was the Achaemenid Empire based?", ["Iranian plateau"]),
    ("Did the Achaemenid Empire include Cyprus?", "yes"),
    ("Whom did Cyrus defeat?", ["Media", "Lydia", "Neo-Babylonian"]),
    ("Who conquered the Achaemenid Empire?", ["Alexander"]),
    ("When was the Achaemenid Empire conquered?", ["330"]),
    ("What were the official languages of the Achaemenid Empire?", ["Persian", "Aramaic"]),
    ("Was the empire repulsed from Greece?", "yes"),
]

Q["History of Africa"] = [
    ("When did archaic humans emerge out of Africa?", ["0.5", "1.8"]),
    ("Where did modern humans emerge?", ["East Africa"]),
    ("Is the oral word revered in most African cultures?", "yes"),
    ("How has history been passed down in Africa?", ["oral"]),
    ("Where did the Tichitt Tradition flourish?", ["West Africa"]),
    ("Where did Ancient Egypt and Kerma arise?", ["northeast"]),
    ("Which modern country did the Bantu expansion sweep from?", ["Cameroon"]),
    ("How many polities did Africa have at its peak?", ["10,000", "10000"]),
    ("Did Islam spread to the Swahili coast?", "yes"),
    ("Were some African societies egalitarian?", "yes"),
]

Q["Age of Enlightenment"] = [
    ("What is the Age of Enlightenment also known as?", ["Age of Reason"]),
    ("Where did the Enlightenment emerge?", ["Europe"]),
    ("When did the Enlightenment reach its peak?", ["18th"]),
    ("Did the Enlightenment promote religious tolerance?", "yes"),
    ("Did Enlightenment thinkers advocate for the separation of church and state?", "yes"),
    ("What did the Enlightenment build upon?", ["Scientific Revolution"]),
    ("Who wrote Discourse on the Method?", ["Descartes"]),
    ("When was the Principia Mathematica published?", ["1687"]),
    ("When did Louis XIV die?", ["1715"]),
    ("When did Immanuel Kant die?", ["1804"]),
]

Q["Algorithm"] = [
    ("Is an algorithm a set of instructions?", "yes"),
    ("Do all algorithms terminate?", "yes"),
    ("What might be applied to problems for which no algorithmic solution can exist?", ["heuristic"]),
    ("Are social media recommender systems accurately classified as heuristics?", "yes"),
    ("Are social media recommender systems algorithms?", "no"),
    ("What do randomized algorithms incorporate?", ["random input"]),
    ("What occurs at each step?", ["computation"]),
    ("In what kind of language can an algorithm be expressed?", ["formal language"]),
]

Q["Trigonometry"] = [
    ("Is trigonometry a branch of mathematics?", "yes"),
    ("What is trigonometry concerned with?", ["angle", "side length", "triangle"]),
    ("What do trigonometric functions relate?", ["angle"]),
    ("When did trigonometry emerge?", ["3rd century"]),
    ("Where did trigonometry emerge?", ["Hellenistic"]),
    ("What did the Greeks focus on?", ["chord"]),
    ("Where were the earliest-known tables of values for trigonometric ratios created?", ["India"]),
    ("Has trigonometry been applied in navigation?", "yes"),
    ("What is trigonometry known for?", ["identities"]),
    ("Is sine a trigonometric ratio?", "yes"),
]

Q["Topology"] = [
    ("Is topology a branch of mathematics?", "yes"),
    ("Is stretching a continuous deformation?", "yes"),
    ("What is a topological space?", ["set"]),
    ("Are metric spaces topological spaces?", "yes"),
    ("Which deformations are considered in topology?", ["homeomorphism", "homotop"]),
    ("What is a property that is invariant under such deformations?", ["topological"]),
    ("Is compactness a topological property?", "yes"),
    ("Who introduced the term topology?", ["Listing"]),
    ("Whose problem was the Seven Bridges of Königsberg?", ["Euler"]),
    ("When did Leibniz envision the geometria situs?", ["17th"]),
]

Q["Variable (mathematics)"] = [
    ("Is a variable a symbol?", "yes"),
    ("What does a variable refer to?", ["object"]),
    ("What is a variable typically?", ["letter"]),
    ("What are the values a variable can take often?", ["number"]),
    ("Which language does the word variable come from?", ["Latin", "variabilis"]),
    ("What was the term variable originally used for?", ["argument"]),
    ("In the equation y = f(x), what is x?", ["argument"]),
    ("In the equation y = f(x), what does f denote?", ["function"]),
    ("Is any valid candidate for the object the value of the variable?", "yes"),
    ("Can p2 = 2 q2 be satisfied when p and q are nonzero integers?", "no"),
]

Q["Calculus"] = [
    ("Is calculus a branch of mathematics?", "yes"),
    ("What does calculus study?", ["change"]),
    ("What was calculus originally called?", ["infinitesimal"]),
    ("How many major branches does calculus have?", ["two", "2"]),
    ("Is integral calculus a branch of calculus?", "yes"),
    ("What does differential calculus study?", ["rates of change", "slope"]),
    ("What relates differential calculus and integral calculus?", ["fundamental theorem"]),
    ("Who formulated infinitesimal calculus?", ["Newton", "Leibniz"]),
    ("When was infinitesimal calculus formulated?", ["17th"]),
    ("What does integral calculus study?", ["accumulation", "area"]),
]

Q["Pay a Self Assessment penalty"] = [
    ("Do you get a penalty if you miss the deadline for submitting a tax return?", "yes"),
    ("Within how many days must you pay the penalty?", ["30"]),
    ("Will you be charged interest if you pay after the deadline?", "yes"),
    ("Can you appeal against a penalty if you have a reasonable excuse?", "yes"),
    ("In which other language is this guide available?", ["Welsh", "Cymraeg"]),
    ("What does how long a payment takes to go through depend on?", ["how you pay"]),
    ("What is HMRC?", ["Revenue"]),
    ("How many characters is the payment reference?", ["11"]),
    ("Where do you set up a Direct Debit?", ["online account"]),
]

Q["Help people who have come to the UK from Afghanistan"] = [
    ("Who can offer work to people arriving from Afghanistan?", ["employer"]),
    ("Do people with refugee status have the same right to work as those born in the UK?", "yes"),
    ("Where do you email the completed form?", ["offerwork"]),
    ("Who will contact you after your offer is received?", ["DWP", "REN", "Department for Work and Pensions", "Refugee Employment Network"]),
    ("What does the Community Sponsorship scheme allow groups to do?", ["support"]),
    ("Who do Community Sponsors receive training from?", ["Reset"]),
    ("Is Reset a charity?", "yes"),
    ("For how long must you commit to offering support to a family?", ["one year", "a year", "1 year"]),
    ("What does DWP stand for?", ["Department for Work and Pensions"]),
]

Q["PSV (Public Service Vehicle) operator licences"] = [
    ("How many types of PSV operator licences are there?", ["4", "four"]),
    ("Do most full-time commercial operators use standard licences?", "yes"),
    ("Does a standard licence let you take passengers abroad?", "yes"),
    ("What can you only apply for a restricted licence for?", ["small-scale"]),
    ("How many vehicles does a restricted licence allow you to use?", ["1 or 2", "two", "2"]),
    ("What are special restricted licences used for?", ["taxi"]),
    ("Who can apply for a special restricted licence?", ["taxi operator"]),
    ("What do you need to run a private bus service in London?", ["London Service Permit"]),
    ("Are there special licensing rules in London?", "yes"),
]

Q["Advanced Learner Loan"] = [
    ("What can an Advanced Learner Loan help with?", ["cost"]),
    ("Does loan eligibility depend on your income?", "no"),
    ("Are there credit checks for an Advanced Learner Loan?", "no"),
    ("Do you need to repay a grant?", "no"),
    ("Who should you ask about grants?", ["college", "training provider"]),
    ("From which fund might you get a grant?", ["adult skills fund", "ASF"]),
    ("Is different funding available if you want to study in Scotland?", "yes"),
    ("From when are you charged interest?", ["first payment"]),
    ("Can you make extra repayments towards your loan?", "yes"),
]

Q["Health and Care Worker visa"] = [
    ("Who does a Health and Care Worker visa allow to come to the UK?", ["medical professional"]),
    ("Must you have a confirmed job offer before you apply for your visa?", "yes"),
    ("Must you be able to understand English?", "yes"),
    ("How long can the visa last before you need to extend it?", ["5", "five"]),
    ("Can you extend your visa as many times as you like?", "yes"),
    ("What is settling permanently in the UK also known as?", ["indefinite leave to remain"]),
    ("After how many years may you be able to apply to settle permanently?", ["5", "five"]),
    ("Does indefinite leave to remain give you the right to work?", "yes"),
    ("Can you do an eligible job with the NHS on this visa?", "yes"),
]

Q["pwd"] = [
    ("What does the pwd module provide access to?", ["password database", "user account"]),
    ("Is the pwd module available on all Unix versions?", "yes"),
    ("In traditional Unix, what does the field pw_passwd usually contain?", ["encrypted"]),
    ("What do most modern unices use?", ["shadow password"]),
    ("Where is the encrypted password stored?", ["/etc/shadow"]),
    ("Is /etc/shadow world readable?", "no"),
    ("Is it system-dependent whether the pw_passwd field contains anything useful?", "yes"),
    ("In what order are all available password database entries returned?", ["arbitrary"]),
]

Q["mimetypes"] = [
    ("What does the mimetypes module convert between?", ["filename", "URL"]),
    ("How many classes does the module provide?", ["one", "1"]),
    ("Are encodings supported for the conversion from MIME type to filename extension?", "no"),
    ("What are the normal interface to this module?", ["function"]),
    ("What is the return value?", ["tuple"]),
    ("When is type None?", ["guess", "missing", "unknown"]),
    ("What is the encoding suitable for use as?", ["Content-Encoding"]),
    ("Is the encoding suitable for use as a Content-Transfer-Encoding header?", "no"),
    ("Are the mappings table driven?", "yes"),
    ("Which programs are given as examples of programs used to encode?", ["compress", "gzip"]),
]

Q["unittest"] = [
    ("What was unittest originally inspired by?", ["JUnit"]),
    ("Does unittest support test automation?", "yes"),
    ("What is a test case?", ["individual unit", "unit of testing"]),
    ("What does a test case check for?", ["response"]),
    ("Which base class does unittest provide?", ["TestCase"]),
    ("What is a test suite?", ["collection"]),
    ("What is a test suite used for?", ["aggregate"]),
    ("What is a test runner?", ["component"]),
    ("May the runner use a graphical interface?", "yes"),
    ("Is a test suite a collection of test cases?", "yes"),
]

Q["wsgiref"] = [
    ("Is wsgiref recommended for production?", "no"),
    ("What is wsgiref?", ["reference implementation"]),
    ("What does WSGI stand for?", ["Web Server Gateway Interface"]),
    ("Is WSGI a standard interface between web server software and web applications?", "yes"),
    ("Who needs to know every detail of the WSGI design?", ["author"]),
    ("Do you need to understand every detail of WSGI to install a WSGI application?", "no"),
    ("What kind of security checks does the module implement?", ["basic"]),
    ("Does wsgiref provide a demo HTTP server?", "yes"),
    ("Which PEP is the WSGI specification?", ["3333"]),
    ("Where can you find more information about WSGI?", ["readthedocs"]),
]

Q["hashlib"] = [
    ("What does the hashlib module implement?", ["interface"]),
    ("Is SHA256 one of the included algorithms?", "yes"),
    ("In which standard is the SHA-3 series defined?", ["202"]),
    ("Is MD5 a legacy algorithm?", "yes"),
    ("In which module are the adler32 and crc32 hash functions?", ["zlib"]),
    ("How many constructor methods are there for each type of hash?", ["one", "1"]),
    ("What do you use to create a SHA-256 hash object?", ["sha256"]),
    ("Which method do you use to feed the object bytes?", ["update"]),
    ("When is the Python GIL released?", ["2047"]),
    ("Which methods give you the digest of the data fed so far?", ["hexdigest"]),
]

Q["Foundation-Style Pretraining for Scalable and Transferable Distributed PV Forecasting"] = [
    ("What is increasing the demand for accurate forecasting?", ["growth"]),
    ("What does the paper present?", ["framework"]),
    ("What kind of forecasting model does the framework learn?", ["shared"]),
    ("How many pretraining objectives are designed?", ["three", "3"]),
    ("Which objective provides the most balanced performance?", ["mixed"]),
    ("How many distributed PV stations are in the experiments?", ["479"]),
    ("How many stations are used for zero-shot evaluation?", ["139"]),
    ("What does NWP stand for?", ["numerical weather prediction"]),
    ("Does the multi-site pretrained model outperform station-specific baselines?", "yes"),
    ("Can the pretrained model be deployed at new PV stations?", "yes"),
]

Q["Annealed correlation and quenched noise sensitivity in biased deep neural networks"] = [
    ("Who did the earlier work?", ["Jonasson", "Steif", "Zetterqvist"]),
    ("When was the earlier work?", ["2023"]),
    ("What activations did the networks have?", ["sign"]),
    ("What do the authors add?", ["bias"]),
    ("Is quenched noise sensitivity retained?", "yes"),
    ("Does the annealed covariance remain bounded away from zero?", "yes"),
    ("What weights did the networks in the earlier work have?", ["Gaussian"]),
    ("Did the networks in the earlier work have bias terms?", "no"),
]

Q["Neural Closed-Loop Identification of Nonlinear Systems with Stability and Generalization Guarantees"] = [
    ("Are neural networks expressive models of nonlinear dynamics?", "yes"),
    ("How many difficulties does identifying such systems from closed-loop data raise?", ["two", "2"]),
    ("What does the feedback loop correlate inputs with?", ["noise"]),
    ("What does ICI stand for?", ["Internal Controller Identification"]),
    ("Which classical parameterization do they generalize?", ["Youla"]),
    ("In the linear case, what does the indirect method reduce to?", ["open-loop identification"]),
    ("Does ICI identify open-loop unstable plants?", "yes"),
    ("Does ICI generalize zero-shot to environments unseen during training?", "yes"),
    ("What does ICI avoid with limited data?", ["overfitting"]),
]

Q["Joints, Camera, Action! Co-Generating 3D Motion and Video for Arbitrary Rigs"] = [
    ("Can video generation models depict realistic motion?", "yes"),
    ("What can a video model show jumping over a crossbar?", ["monkey"]),
    ("Can a video model return the jump as replayable 3D motion?", "no"),
    ("What does the model co-generate?", ["video", "motion"]),
    ("What do prior video-motion models often add?", ["parameters", "billions"]),
    ("Where do they keep 3D motion?", ["separate model"]),
    ("How do they connect the motion model to a pretrained video model?", ["cross-attention"]),
    ("What does the model learn to locate in the video frames?", ["joint"]),
    ("How many training pairs does this yield?", ["200K", "200"]),
    ("What do they use to place animated 3D assets in scenes?", ["editor"]),
]

Q["ABACUS: A Benchmark for Image Editing Models to Assess Object Category and Counting Under Scene Conservation"] = [
    ("What is ABACUS?", ["benchmark"]),
    ("Do image editing models often fail to produce the correct number?", "yes"),
    ("Is the ABACUS protocol judge-free?", "yes"),
    ("Are VLM judges good at counting?", "no"),
    ("What does a VLM only confirm?", ["category"]),
    ("What does the method reveal?", ["failure"]),
    ("Has the true numerical ability of today's editing models been accurately measured?", "no"),
    ("What do the failures worsen with?", ["complexity", "object count"]),
    ("What does VLM stand for?", ["vision-language model"]),
]

Q["openssh_2k.log lines 38-47"] = [
    ("For which user did the passwords fail?", ["root"]),
    ("From which address did the failed passwords come?", ["112.95.230.3"]),
    ("How many failed password attempts are there?", ["four", "4"]),
    ("Did authentication succeed for root?", "no"),
    ("On which host is sshd running?", ["LabSZ"]),
    ("From which port did the first failed password come?", ["47068"]),
    ("At what time was the first failed password?", ["07:27:55"]),
    ("Did 112.95.230.3 disconnect?", "yes"),
    ("On which date are these entries?", ["Dec 10"]),
]

Q["openssh_2k.log lines 111-120"] = [
    ("How many failed password attempts were there?", ["three", "3"]),
    ("From which addresses did the failed passwords come?", ["112.95.230.3", "123.235.32.19"]),
    ("Was there an authentication failure for root from 123.235.32.19?", "yes"),
    ("From which port did the failed password from 123.235.32.19 come?", ["40652"]),
    ("When was the authentication failure from 123.235.32.19?", ["07:32:24"]),
    ("Which user had authentication failures?", ["root"]),
    ("Was the password from 123.235.32.19 accepted?", "no"),
    ("What was the process id of sshd at 07:32:24?", ["24287"]),
]

Q["openssh_2k.log lines 1396-1405"] = [
    ("From which address did the failed passwords come?", ["183.62.140.253"]),
    ("How many failed password attempts were there?", ["four", "4"]),
    ("For which user did the passwords fail?", ["root"]),
    ("Did 183.62.140.253 disconnect?", "yes"),
    ("At what time was the last failed password?", ["10:58:39"]),
    ("From which port did the last failed password come?", ["52590"]),
    ("Was there an authentication failure for root?", "yes"),
]

Q["linux_2k.log lines 1280-1289"] = [
    ("For which users were sessions opened?", ["cyrus", "news"]),
    ("By whom was the session for user cyrus opened?", ["uid=0"]),
    ("Was the session for user news closed?", "yes"),
    ("What exited abnormally?", ["logrotate"]),
    ("How many authentication failures were there?", ["five", "5"]),
    ("From which host did the authentication failures come?", ["202-132-40-29.adsl.ttn.net"]),
    ("Which user did the authentication failures target?", ["root"]),
    ("What is the name of the machine?", ["combo"]),
]

Q["linux_2k.log lines 1202-1211"] = [
    ("How many authentication failures were there?", ["ten", "10"]),
    ("From which address did the authentication failures come?", ["150.183.249.110"]),
    ("For which user did authentication fail?", ["root"]),
    ("When was the first authentication failure?", ["16:03:05"]),
    ("Did all the authentication failures come from the same address?", "yes"),
    ("Did authentication succeed for root?", "no"),
    ("On which date are these entries?", ["Jul 10"]),
]

Q["Roblox player uncovers cheating, awarded Guinness World Record"] = [
    ("Who was recognized by Guinness World Records?", ["Delaere", "Quinten"]),
    ("How old is Delaere?", ["18"]),
    ("On which platform did Delaere expose cheating?", ["Roblox"]),
    ("What is Delaere known as online?", ["kannotlogin"]),
    ("What did Delaere use to demonstrate the cheating?", ["data analysis"]),
    ("Which game was the speed-running event for?", ["Ultimate Easy Obby"]),
    ("What time did Delaere post?", ["48.96"]),
    ("How many unknown accounts posted times around 5 minutes and 42 seconds?", ["three", "3"]),
    ("Was the event a collaboration between Roblox and Guinness World Records?", "yes"),
    ("Where did Delaere post that the times were humanly impossible?", ["Reddit"]),
]

Q["At least 20 die in Odesa in Russian missile strike, Ukraine reports"] = [
    ("How many people died in Odesa?", ["20"]),
    ("How many people were injured?", ["70"]),
    ("On what date did the attack occur?", ["March 15"]),
    ("How many Iskander-M missiles were fired?", ["two", "2"]),
    ("From where were the missiles fired?", ["Crimea"]),
    ("Was a paramedic among the dead?", "yes"),
    ("How many times did Russian troops fire missiles at Odesa?", ["twice", "two"]),
    ("When was the second missile fired?", ["rescuers", "eliminating"]),
    ("How many employees of the State Emergency Service are among the victims?", ["seven", "7"]),
    ("What was damaged?", ["infrastructure", "residential buildings", "vehicles"]),
]

Q["Brazil's supreme court sentences former president Jair Bolsonaro to 27 years in prison"] = [
    ("Who sentenced Bolsonaro?", ["court", "justices"]),
    ("How long is Bolsonaro's sentence?", ["27 years"]),
    ("How many justices formed the panel?", ["five", "5"]),
    ("How many justices voted to convict Bolsonaro?", ["four", "4"]),
    ("Which justice voted to acquit Bolsonaro?", ["Fux"]),
    ("On which day was the ruling announced?", ["Thursday"]),
    ("The result of which election did the alleged plot aim to overturn?", ["2022"]),
    ("Where were government buildings stormed?", ["Brasília", "Brasilia"]),
    ("How many co-conspirators were also convicted?", ["seven", "7"]),
    ("Did Bolsonaro deny the allegations?", "yes"),
]

Q["Massachusetts Institute of Technology engineers tap access to battery-less desalination of more groundwater than ever before"] = [
    ("Which institute were the engineers from?", ["Massachusetts Institute of Technology", "MIT"]),
    ("In which journal did the engineers publish?", ["Nature Water"]),
    ("Is the new desalination plant technology battery-less?", "yes"),
    ("Where was the prototype tested?", ["Alamogordo", "New Mexico", "Brackish Groundwater"]),
    ("How much water did the prototype desalinate per day?", ["5,000", "5000"]),
    ("What is the system designed to process?", ["brackish"]),
    ("What does the system adjust several times a second?", ["desalination rate"]),
    ("Is the desalination plant technology solar?", "yes"),
]

Q["Labour becomes largest party in UK local government after 2023 English elections"] = [
    ("Which party became the largest party in UK local government?", ["Labour"]),
    ("Since when had Labour been in the minority in local government?", ["2002"]),
    ("For how many local government authorities did elections occur?", ["230"]),
    ("How many seats did Labour gain?", ["635"]),
    ("How many authorities did the Conservatives lose?", ["45"]),
    ("Which council did Labour lose control of?", ["Slough"]),
    ("Which authority did the Green Party win control of?", ["Mid Suffolk"]),
    ("Who is the Labour Party leader?", ["Starmer", "Keir"]),
    ("Did the Green Party achieve their best local election results ever?", "yes"),
    ("How many seats did the Liberal Democrats flip?", ["416"]),
]

Q["The House of Representatives"] = [
    ("How often are the Members of the House of Representatives chosen?", ["second year", "two years", "every two"]),
    ("Who chooses the Members of the House?", ["People"]),
    ("What age must a Representative have attained?", ["twenty five", "25"]),
    ("Can a person who is twenty years old be a Representative?", "no"),
    ("How many years must a Representative have been a Citizen of the United States?", ["seven", "7"]),
    ("Can a person who has been a citizen for three years be a Representative?", "no"),
    ("Who issues Writs of Election to fill vacancies?", ["Executive"]),
    ("Who chooses the Speaker of the House?", ["Representatives"]),
    ("Does the House of Representatives have the sole Power of Impeachment?", "yes"),
    ("Must a Representative be an Inhabitant of the State in which he is chosen?", "yes"),
]

Q["The Senate"] = [
    ("How many Senators does each State have?", ["two", "2"]),
    ("For how many years are Senators chosen?", ["six", "6"]),
    ("How many votes does each Senator have?", ["one", "1"]),
    ("What age must a Senator have attained?", ["thirty", "30"]),
    ("Can a person who is twenty-eight years old be a Senator?", "no"),
    ("How many years must a Senator have been a Citizen of the United States?", ["nine", "9"]),
    ("Who is the President of the Senate?", ["Vice President"]),
    ("When does the Vice President have a vote in the Senate?", ["divided"]),
    ("Who chooses the Senators?", ["Legislature"]),
]

Q["The President"] = [
    ("In whom is the executive Power vested?", ["President"]),
    ("What age must a person have attained to be eligible to the Office of President?", ["thirty five", "35"]),
    ("Is a person who is thirty years old eligible to the Office of President?", "no"),
    ("How many years must a person have been a Resident within the United States to be eligible to the Office of President?", ["fourteen", "14"]),
    ("Who becomes President if the President resigns?", ["Vice President"]),
    ("Does the Vice President become President on the death of the President?", "yes"),
]

Q["The right to vote"] = [
    ("Can the right of citizens to vote be denied on account of race?", "no"),
    ("Can the right of citizens to vote be denied on account of sex?", "no"),
    ("Can the right to vote of a citizen who is eighteen be denied on account of age?", "no"),
    ("Can a State deny the right of citizens to vote on account of color?", "no"),
    ("From what age can the right to vote not be denied on account of age?", ["eighteen", "18"]),
]

Q["Terms of office"] = [
    ("How many times can a person be elected to the office of the President?", ["twice", "two"]),
    ("Can a person be elected to the office of the President three times?", "no"),
    ("When do the terms of the President and Vice President end?", ["20th", "January"]),
    ("On which day of January do the terms of Senators and Representatives end?", ["3d"]),
    ("At what time of day do the terms end?", ["noon"]),
]
