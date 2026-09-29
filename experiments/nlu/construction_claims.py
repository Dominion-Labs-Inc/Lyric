"""What each construction SHOULD read as. The bar is CORRECTNESS, not presence:
counting readings rewards a glued garbage atom exactly the way counting refusals
rewarded silence. A claim is (subject, relation, object|None, positive);
comparison strips articles, case and plural -s.
"""

EXPECTED = [
 ("copular", [
   ("A robin is a bird.",        [("robin","is","bird",True)]),
   ("The vault is locked.",      [("vault","is","locked",True)]),
   ("A crucible is a vessel.",   [("crucible","is","vessel",True)]),
 ]),
 ("copular negated", [
   ("A robin is not a mammal.",  [("robin","is","mammal",False)]),
   ("The engine is not cold.",   [("engine","is","cold",False)]),
   ("The turbine is not silent.",[("turbine","is","silent",False)]),
 ]),
 ("subject-verb-object", [
   ("The kidney filters plasma.",[("kidney","filters","plasma",True)]),
   ("The tank stores water.",    [("tank","stores","water",True)]),
   ("A crucible melts ore.",     [("crucible","melts","ore",True)]),
 ]),
 ("multi-word subject", [
   ("The control rod is heavy.", [("control rod","is","heavy",True)]),
   ("The smoke alarm is red.",   [("smoke alarm","is","red",True)]),
   ("The heat exchanger is hot.",[("heat exchanger","is","hot",True)]),
 ]),
 ("relative clause", [
   ("The pump that failed was replaced.",
      [("pump","failed",None,True), ("pump","was replaced",None,True)]),
   ("The valve which leaked is closed.",
      [("valve","leaked",None,True), ("valve","is","closed",True)]),
   ("The engineer who arrived is waiting.",
      [("engineer","arrived",None,True), ("engineer","is","waiting",True)]),
 ]),
 ("NP coordination", [
   ("Dogs and cats are mammals.",
      [("dog","is","mammal",True), ("cat","is","mammal",True)]),
   ("Iron and copper are metals.",
      [("iron","is","metal",True), ("copper","is","metal",True)]),
   ("Rain and snow are precipitation.",
      [("rain","is","precipitation",True), ("snow","is","precipitation",True)]),
 ]),
 ("object coordination", [
   ("The vault holds gold and silver.",
      [("vault","holds","gold",True), ("vault","holds","silver",True)]),
   ("The reactor vents steam and heat.",
      [("reactor","vents","steam",True), ("reactor","vents","heat",True)]),
   ("The tank stores water and oil.",
      [("tank","stores","water",True), ("tank","stores","oil",True)]),
 ]),
 ("VP coordination", [
   ("The valve opens and closes.",
      [("valve","opens",None,True), ("valve","closes",None,True)]),
   ("The engine starts and stops.",
      [("engine","starts",None,True), ("engine","stops",None,True)]),
   ("The pump primes and runs.",
      [("pump","primes",None,True), ("pump","runs",None,True)]),
 ]),
 ("subordination", [
   ("Because the valve stuck the tank overflowed.",
      [("valve","stuck",None,True), ("tank","overflowed",None,True)]),
   ("Although the pump ran the tank stayed empty.",
      [("pump","ran",None,True), ("tank","stayed","empty",True)]),
   ("When the alarm sounded the door closed.",
      [("alarm","sounded",None,True), ("door","closed",None,True)]),
 ]),
 ("complement clause", [
   ("Scientists believe the universe is expanding.",
      [("universe","is","expanding",True)]),
   ("Engineers know the bridge is safe.",
      [("bridge","is","safe",True)]),
   ("The report says the valve is faulty.",
      [("valve","is","faulty",True)]),
 ]),
 ("ditransitive", [
   ("Alice gave Bob a book.",
      [("alice","gave","book",True), ("alice","gave to","bob",True)]),
   ("The clerk handed the customer a receipt.",
      [("clerk","handed","receipt",True), ("clerk","handed to","customer",True)]),
   ("The teacher told the class a story.",
      [("teacher","told","story",True), ("teacher","told to","class",True)]),
 ]),
 ("apposition", [
   ("Paris the capital of France is on the Seine.",
      [("paris","is","capital of france",True), ("paris","on","seine",True)]),
   ("Mercury the smallest planet orbits fastest.",
      [("mercury","is","smallest planet",True), ("mercury","orbits",None,True)]),
   ("Copper a soft metal conducts heat.",
      [("copper","is","soft metal",True), ("copper","conducts","heat",True)]),
 ]),
 ("comparative", [
   ("Iron is heavier than aluminium.", [("iron","heavier than","aluminium",True)]),
   ("Gold is denser than silver.",     [("gold","denser than","silver",True)]),
   ("Steel is stronger than tin.",     [("steel","stronger than","tin",True)]),
 ]),
 ("quantified", [
   ("Most birds can fly.",  [("bird","can fly",None,True)]),
   ("Some metals rust.",    [("metal","rust",None,True)]),
   ("Many rivers flood.",   [("river","flood",None,True)]),
 ]),
 ("passive", [
   ("The letter was written by Alice.",   [("alice","written","letter",True)]),
   ("The bridge was built by engineers.", [("engineer","built","bridge",True)]),
   ("The valve was closed by the operator.",[("operator","closed","valve",True)]),
 ]),
 ("possessive", [
   ("France's capital is Paris.",     [("capital of france","is","paris",True)]),
   ("The engine's housing is cracked.",[("housing of engine","is","cracked",True)]),
   ("Alice's report is late.",        [("report of alice","is","late",True)]),
 ]),
 ("modal", [
   ("A pump can fail.",       [("pump","can fail",None,True)]),
   ("The valve may stick.",   [("valve","may stick",None,True)]),
   ("The tank might overflow.",[("tank","might overflow",None,True)]),
 ]),
 ("prepositional claim", [
   ("The cup is in the box.",     [("cup","in","box",True)]),
   ("The vault is under the bank.",[("vault","under","bank",True)]),
   ("The sensor is on the pipe.", [("sensor","on","pipe",True)]),
 ]),
 ("multi-clause definition", [
   ("A function is a reusable block of code that encapsulates logic.",
      [("function","is","reusable block of code",True),
       ("reusable block of code","encapsulates","logic",True)]),
   ("A pump is a device that moves fluid through a pipe.",
      [("pump","is","device",True),
       ("device","moves","fluid",True)]),
   ("A memristor is a component whose resistance depends on charge.",
      [("memristor","is","component",True),
       ("resistance of component","depends on","charge",True)]),
 ]),
]
