"""Concept catalog: the layer between recipe ingredients and stock items.

Recipes (often English) and the pantry's items (German product lines)
meet on *concepts* — canonical food identities with bilingual aliases.
Resolution is a dictionary lookup plus small deterministic rules, never a
live LLM call. The seed below is curated and reviewable in git; cloud
proposals are only ever written after a user confirmed them.

Resolution tiers, best first:
  identity    an in-stock item carries the same concept
  variant     same concept, different form (seeds vs pods, dried vs fresh)
  in_blend    the concept is a component of a stocked blend ("cloves" ->
              the five-spice mix on the shelf)
  sibling     close culinary kin with a sensory-drift note
  components  the recipe wants a blend the pantry lacks but >=50% of its
              parts are stocked ("mix your own garam masala")
  buy         concept known, nothing stocked -> suggest the German buy name
  unknown     not in the catalog (backlog for the guarded cloud pass)
"""

import re

# ==========================================================================
# Seed registry. Keys are stable ids; aliases are lowercase after
# normalization and must be unambiguous — the "Kümmel vs Kreuzkümmel" class
# of confusion is decided HERE, in reviewable data, not by fuzzing.
# ==========================================================================
CONCEPTS: dict[str, dict] = {
    # --- spices & spice forms --------------------------------------------
    "salt": {"de": "Salz", "en": "salt", "family": "spice", "aliases": [
        "salt", "sea salt", "kosher salt", "cooking salt", "fine sea salt",
        "sea salt flakes", "salt flakes", "table salt", "meersalz", "salz",
        "alpensalz grob", "salz für das kochwasser"]},
    "black_pepper": {"de": "Pfeffer", "en": "black pepper", "family": "spice",
        "aliases": ["black pepper", "black peppercorns", "peppercorns",
                    "ground black pepper", "cracked black pepper",
                    "freshly ground black pepper", "schwarzer pfeffer",
                    "pfeffer", "pfeffer schwarz"]},
    "white_pepper": {"de": "Weißer Pfeffer", "en": "white pepper",
        "family": "spice", "aliases": ["white pepper", "weisser pfeffer",
        "weißer pfeffer", "pfeffer, weiß", "pfeffer, weiss"]},
    "cinnamon": {"de": "Zimt", "en": "cinnamon", "family": "spice",
        "aliases": ["cinnamon", "ground cinnamon", "ceylon cinnamon",
                    "cassia", "zimt", "ceylon zimt", "zimtpulver"]},
    "cinnamon_stick": {"de": "Zimtstangen", "en": "cinnamon sticks",
        "family": "spice", "aliases": ["cinnamon stick", "cinnamon sticks",
        "zimtstange", "zimtstangen"], "variant_of": "cinnamon",
        "variant_note": "Stangen mitreiben oder ganz mitkochen und entfernen"},
    "cardamom": {"de": "Kardamom", "en": "cardamom", "family": "spice",
        "aliases": ["cardamom", "green cardamom", "ground cardamom",
        "cardamom pods", "green cardamom pod", "green cardamom pods",
        "kardamom", "kardamom saat", "cardamom seeds", "kardamomkapseln",
        "elaichi"],
        "variant_note": "Samen aus den Kapseln lösen und im Mörser anquetschen"},
    "black_cardamom": {"de": "Schwarzer Kardamom", "en": "black cardamom",
        "family": "spice", "aliases": ["black cardamom", "schwarzer kardamom"],
        "sibling_of": ["cardamom"],
        "sibling_note": "Schwarzer Kardamom raucht kräftig — sparsam verwenden"},
    "cloves": {"de": "Gewürznelken", "en": "cloves", "family": "spice",
        "aliases": ["cloves", "whole cloves", "clove", "gewürznelken",
        "nelken", "gewürznelke"]},
    "star_anise": {"de": "Sternanis", "en": "star anise", "family": "spice",
        "aliases": ["star anise", "sternanis", "badian"]},
    "fennel_seeds": {"de": "Fenchelsamen", "en": "fennel seeds",
        "family": "spice", "aliases": ["fennel seeds", "fennel seed",
        "fenchelsamen"]},
    "szechuan_pepper": {"de": "Szechuanpfeffer", "en": "szechuan pepper",
        "family": "spice", "aliases": ["szechuan pepper",
        "szechuan peppercorns", "szechuanpfeffer", "sichuan pepper"]},
    "cumin": {"de": "Kreuzkümmel", "en": "cumin", "family": "spice",
        "aliases": ["cumin", "ground cumin", "cumin seeds", "cumin seed",
        "cumin powder", "kreuzkümmel", "kreuzkümmel gemahlen",
        "kreuzkümmel saat", "jeera"]},
    "caraway": {"de": "Kümmel", "en": "caraway", "family": "spice",
        "aliases": ["caraway", "caraway seeds", "kümmel"]},
    "coriander_seed": {"de": "Koriander (Gewürz)", "en": "coriander seeds",
        "family": "spice", "aliases": ["coriander seeds", "coriander seed",
        "ground coriander", "coriander powder", "koriander",
        "koriandersaat", "koriander gemahlen", "korianderpulver"]},
    "turmeric": {"de": "Kurkuma", "en": "turmeric", "family": "spice",
        "aliases": ["turmeric", "ground turmeric", "turmeric powder",
        "curcuma", "kurkuma", "kurkuma pulver", "gelbwurz"]},
    "chili_ground": {"de": "Chili (gemahlen)", "en": "chilli powder",
        "family": "spice", "aliases": ["chilli powder", "chili powder",
        "chilli flakes", "chili flakes", "dried chilli flakes",
        "chiliflocken", "chilis gemahlen", "cayenne", "cayenne pepper",
        "cayennepfeffer", "kashmiri chilli powder",
        "kashmiri red chilli powder"]},
    "paprika_sweet": {"de": "Paprika edelsüß", "en": "sweet paprika",
        "family": "spice", "aliases": ["paprika", "sweet paprika",
        "paprika powder", "paprika edelsüss", "paprika edelsuess",
        "edelsüss paprika", "mild paprika powder"]},
    "paprika_smoked": {"de": "Geräucherte Paprika",
        "en": "smoked paprika", "family": "spice",
        "aliases": ["smoked paprika", "geräucherte paprika",
        "pimenton de la vera"], "sibling_of": ["paprika_sweet"],
        "sibling_note": "Edelsüß statt geräuchert: Farbe passt, Raucharoma fehlt"},
    "fenugreek_seed": {"de": "Bockshornklee", "en": "fenugreek seeds",
        "family": "spice", "aliases": ["fenugreek seeds", "fenugreek",
        "bockshornklee", "methi seeds"]},
    "kasoori_methi": {"de": "Kasuri Methi", "en": "dried fenugreek leaves",
        "family": "herb_dried", "aliases": ["kasoori methi", "kasuri methi",
        "dried fenugreek leaves", "methi leaves"],
        "variant_of": "fenugreek_seed",
        "variant_note": "Bockshornkleesamen grob mörsern — ähnliches Bitter-Aroma"},
    "nutmeg": {"de": "Muskatnuss", "en": "nutmeg", "family": "spice",
        "aliases": ["nutmeg", "muskatnuss", "muskat", "ground nutmeg",
        "mace", "muskatblüte"]},
    "allspice": {"de": "Piment", "en": "allspice", "family": "spice",
        "aliases": ["allspice", "piment", "pimenta", "jamaicapfeffer"]},
    "chipotle": {"de": "Chipotle in Adobo", "en": "chipotle in adobo",
        "family": "pantry_conserve", "aliases": ["chipotle",
        "chipotle peppers in adobo sauce", "chipotle in adobo",
        "chipotles in adobo"]},
    "sumac_tajin": {"de": "Tajin", "en": "tajin", "family": "spice",
        "aliases": ["tajin", "tajín", "sumac", "sumach"]},

    # --- blends (component lists in BLENDS) --------------------------------
    "five_spice": {"de": "Fünf-Gewürze-Mischung", "en": "chinese five spice",
        "family": "blend", "aliases": ["chinese five spice", "five spice",
        "5 spice", "fünf gewürz mischung", "5 gewürtz mischung",
        "fünf-gewürze", "5-spice"]},
    "garam_masala": {"de": "Garam Masala", "en": "garam masala",
        "family": "blend", "aliases": ["garam masala", "garam massala"]},
    "biryani_masala": {"de": "Biryani Masala", "en": "biryani masala",
        "family": "blend", "aliases": ["biryani masala"],
        "sibling_of": ["garam_masala"],
        "sibling_note": "Garam Masala geht für Biryani Masala — leicht anderes Profil"},
    "curry_powder": {"de": "Currypulver", "en": "curry powder",
        "family": "blend", "aliases": ["curry powder", "curry",
        "madras curry powder", "currypulver"]},
    "italian_herbs": {"de": "Italienische Kräuter",
        "en": "italian herbs", "family": "blend",
        "aliases": ["italian herbs", "italian herb mix", "mixed herbs",
        "italienische kräutermischung", "italienische krautermischung",
        "herbes de provence", "pizza kräuter", "pizza krauter"]},
    "brotgewuerz": {"de": "Brotgewürz", "en": "bread spice",
        "family": "blend", "aliases": ["brotgewürtz rustikal",
        "brotgewürz rustikal", "brotgewürz", "brotgewuerz"]},
    "lemon_pepper_mix": {"de": "Zitronenpfeffer", "en": "lemon pepper",
        "family": "blend", "aliases": ["zitronenpfeffer", "lemon pepper",
        "gewürzmischung zitronenpfeffer"]},
    "cajun": {"de": "Cajun", "en": "cajun", "family": "blend",
        "aliases": ["cajun", "cajun spice", "cajun gewürz", "old bay",
        "veggie rub", "smoky burger"]},

    # --- dried & fresh herbs -----------------------------------------------
    "bay_leaf": {"de": "Lorbeerblätter", "en": "bay leaves",
        "family": "herb_dried", "aliases": ["bay leaves", "bay leaf",
        "dried bay leaves", "lorbeer", "lorbeerblätter", "lorbeerblatt"]},
    "oregano": {"de": "Oregano", "en": "oregano", "family": "herb_dried",
        "aliases": ["oregano", "dried oregano"]},
    "thyme": {"de": "Thymian", "en": "thyme", "family": "herb_dried",
        "aliases": ["thyme", "dried thyme", "thymian"]},
    "rosemary": {"de": "Rosmarin", "en": "rosemary", "family": "herb_dried",
        "aliases": ["rosemary", "rosemary leaves", "rosmarin"]},
    "basil_dried": {"de": "Basilikum (getrocknet)", "en": "dried basil",
        "family": "herb_dried",
        "aliases": ["dried basil", "basil"],
        "variant_of": "basil_fresh",
        "variant_note": "Getrocknet: ca. 1/3 der frischen Menge verwenden"},
    "basil_fresh": {"de": "Basilikum", "en": "fresh basil",
        "family": "herb_fresh", "aliases": ["fresh basil",
        "fresh basil leaves", "basil leaves", "basilikum"]},
    "mint": {"de": "Minze", "en": "mint", "family": "herb_fresh",
        "aliases": ["mint", "fresh mint", "mint leaves",
        "small bunch of mint", "pfefferminze"]},
    "parsley": {"de": "Petersilie", "en": "parsley", "family": "herb_fresh",
        "aliases": ["parsley", "flat leaf parsley", "flat-leaf parsley",
        "fresh parsley", "glatte petersilie", "petersilie",
        "italian parsley"]},
    "coriander_fresh": {"de": "Koriandergrün", "en": "fresh coriander",
        "family": "herb_fresh",
        "aliases": ["fresh coriander", "coriander leaves", "cilantro",
        "koriandergrün", "small bunch of coriander"]},
    "curry_leaves": {"de": "Curryblätter", "en": "curry leaves",
        "family": "herb_fresh", "aliases": ["curry leaves", "curry blätter",
        "kadi patta"]},
    "dill": {"de": "Dill", "en": "dill", "family": "herb_fresh",
        "aliases": ["dill", "fresh dill", "dillspitzen"]},

    # --- oils -----------------------------------------------------------------
    "olive_oil": {"de": "Olivenöl", "en": "olive oil", "family": "oil",
        "aliases": ["olive oil", "extra virgin olive oil", "olivenöl",
        "natives olivenöl"]},
    "neutral_oil": {"de": "Rapsöl", "en": "vegetable oil",
        "family": "oil", "aliases": ["rapeseed oil", "canola", "canola oil",
        "rapsöl", "vegetable oil", "neutral oil",
        "neutral-flavoured oil", "oil", "cooking oil", "bratöl",
        "sunflower oil", "sonnenblumenöl"]},
    "peanut_oil": {"de": "Erdnussöl", "en": "peanut oil", "family": "oil",
        "aliases": ["peanut oil", "erdnussöl"]},
    "sesame_oil": {"de": "Sesamöl", "en": "sesame oil", "family": "oil",
        "aliases": ["sesame oil", "toasted sesame oil", "sesamöl",
        "sesamöl geröstet", "geröstetes sesamöl"]},
    "chili_oil": {"de": "Chili-Öl", "en": "chili crisp",
        "family": "oil", "aliases": ["chili oil", "chilli oil", "chili crisp",
        "chilli crisp", "crispy chili oil"]},

    # --- vinegars --------------------------------------------------------------
    "rice_vinegar": {"de": "Reisessig", "en": "rice vinegar",
        "family": "vinegar", "aliases": ["rice vinegar", "reisessig"]},
    "vinegar_mild_white": {"de": "Weißer Essig", "en": "mild white vinegar",
        "family": "vinegar", "aliases": ["condimento bianco",
        "white wine vinegar", "mild white vinegar", "weinessig"],
        "sibling_of": ["rice_vinegar"],
        "sibling_note": "Milder weißer Essig für Reisessig: etwas fruchtiger"},
    "vinegar_apple": {"de": "Apfelessig", "en": "apple cider vinegar",
        "family": "vinegar", "aliases": ["apple cider vinegar",
        "apfelessig", "cider vinegar"]},
    "vinegar_balsamic": {"de": "Aceto Balsamico", "en": "balsamic vinegar",
        "family": "vinegar", "aliases": ["balsamic vinegar", "balsamic",
        "aceto balsamico", "balsamico"]},

    # --- sugar & sweeteners ------------------------------------------------------
    "sugar_white": {"de": "Zucker", "en": "sugar", "family": "sugar",
        "aliases": ["sugar", "caster sugar", "granulated sugar",
        "white sugar", "zucker"]},
    "sugar_brown": {"de": "Brauner Zucker", "en": "brown sugar",
        "family": "sugar", "aliases": ["brown sugar", "light brown sugar",
        "dark brown sugar", "muscovado", "brauner zucker", "demerara"],
        "variant_of": "sugar_white",
        "variant_note": "Weißer Zucker + ein Hauch Melasse/Malz geht auch"},
    "sugar_powdered": {"de": "Puderzucker", "en": "powdered sugar",
        "family": "sugar", "aliases": ["powdered sugar", "icing sugar",
        "puderzucker", "vanillinzucker", "vanilla sugar"],
        "variant_of": "sugar_white",
        "variant_note": "Puderzucker feiner als Kristallzucker"},
    "maple_syrup": {"de": "Ahornsirup", "en": "maple syrup",
        "family": "sugar", "aliases": ["maple syrup", "pure maple syrup",
        "ahornsirup"]},
    "golden_syrup": {"de": "Golden Syrup", "en": "golden syrup",
        "family": "sugar", "aliases": ["golden syrup", "light treacle"],
        "sibling_of": ["maple_syrup", "honey"],
        "sibling_note": "Ahornsirup/Honig statt Golden Syrup: süß genug, feinere Karamellnote"},
    "honey": {"de": "Honig", "en": "honey", "family": "sugar",
        "aliases": ["honey", "honig", "blütenhonig"]},

    # --- flours, grains, starch ----------------------------------------------
    "flour_ap": {"de": "Mehl (Type 405/550)", "en": "all-purpose flour",
        "family": "flour", "aliases": ["plain flour", "all-purpose flour",
        "all purpose flour", "flour", "weizenmehl", "mehl", "type 550",
        "type 405", "type 00 flour", "type 00", "00 flour", "00 pizza flour",
        "pizza flour", "bio spezialmehl für pizza"]},
    "flour_bread": {"de": "Brotmehl (Type 1050)", "en": "bread flour",
        "family": "flour", "aliases": ["bread flour", "strong white flour",
        "high protein flour", "manitoba", "dinkelmehl 1050", "dinkelmehl",
        "roggenmehl type 1150", "roggenmehl 1150"],
        "sibling_of": ["flour_ap"],
        "sibling_note": "Höhere Typezahl: mehr Geschmack, braucht etwas mehr Flüssigkeit"},
    "flour_wholemeal": {"de": "Vollkornmehl", "en": "wholemeal flour",
        "family": "flour", "aliases": ["wholemeal flour",
        "wholemeal plain flour", "whole wheat flour", "vollkornmehl"],
        "sibling_of": ["flour_ap"],
        "sibling_note": "Vollkorn macht Teige dichter und saftiger"},
    "flour_self_raising": {"de": "Selbstbackendes Mehl",
        "en": "self raising flour", "family": "flour",
        "aliases": ["self raising flour", "self-raising flour",
        "self-rising flour"],
        "sibling_of": ["flour_ap"],
        "sibling_note": "Normal Mehl + je 150 g ein TL Backpulver"},
    "flour_buckwheat": {"de": "Buchweizenmehl", "en": "buckwheat flour",
        "family": "flour", "aliases": ["buckwheat flour", "buchweizenmehl",
        "buckwheat"], "sibling_of": ["flour_ap"],
        "sibling_note": "Buchweizen: nussig, glutenfrei — Struktur weicht ab"},
    "semolina": {"de": "Semola", "en": "semolina", "family": "flour",
        "aliases": ["semolina", "semola", "hartweizengrieß", "grieß",
        "durum wheat flour"]},
    "oats": {"de": "Haferflocken", "en": "rolled oats", "family": "grain",
        "aliases": ["rolled oats", "porridge oats", "oats", "haferflocken",
        "hafer", "hafer geschält", "bio hafer geschält"]},
    "cornflour": {"de": "Speisestärke", "en": "cornflour",
        "family": "starch", "aliases": ["cornflour", "cornstarch",
        "corn flour", "speisestärke", "maizena"]},
    "rice_basmati": {"de": "Basmatireis", "en": "basmati rice",
        "family": "grain", "aliases": ["basmati rice", "aged basmati rice",
        "basmati", "basmatireis", "basmati reis", "aufgeweichter basmati reis"]},
    "rice_arborio": {"de": "Risottoreis", "en": "arborio rice",
        "family": "grain", "aliases": ["arborio rice", "risotto rice",
        "risottoreis", "risotto", "carnaroli"],
        "sibling_of": ["rice_basmati"],
        "sibling_note": "Milchreis/Risottokorn für Basmati: klebrig statt körnig-luftig"},
    "rice_long_grain": {"de": "Langkornreis", "en": "long grain rice",
        "family": "grain", "aliases": ["long grain rice", "jasmine rice",
        "langkornreis", "white rice", "reis"]},
    "rice_noodles": {"de": "Reisnudeln", "en": "rice noodles",
        "family": "pasta", "aliases": ["rice noodles", "reisnudeln",
        "vermicelli", "faden nudeln", "glass noodles",
        "nudeln aus naturreis"]},

    # --- pasta -------------------------------------------------------------------
    "pasta_short": {"de": "Kurze Nudeln (Penne & Co.)", "en": "penne",
        "family": "pasta", "aliases": ["penne", "penne rigate",
        "penne rigate nº 41", "frischei-nudeln", "frischei nudeln",
        "rigatoni", "maccheroni", "macaroni",
        "elbow pasta", "dried elbow pasta", "fusilli", "hörnchen",
        "hörnchen, nudeln", "kritharaki", "orecchiette", "casarecce"]},
    "pasta_long": {"de": "Spaghetti", "en": "spaghetti", "family": "pasta",
        "aliases": ["spaghetti", "spaghetti al nero di seppia", "linguine",
        "tagliatelle", "nudeln", "nudeln long"]},
    "pasta_fresh_ramen": {"de": "Ramen-Nudeln", "en": "ramen noodles",
        "family": "pasta", "aliases": ["fresh ramen noodles", "ramen noodles",
        "ramen", "ramen nudeln", "ramennudeln", "alkaline noodles",
        "instant ramen"]},

    # --- tomato ---------------------------------------------------------------------
    "tomato_passata": {"de": "Passierte Tomaten", "en": "tomato passata",
        "family": "tomato", "aliases": ["tomato passata", "passata",
        "passierte tomaten", "tomato puree", "strained tomatoes"]},
    "tomato_canned": {"de": "Tomaten (Dose)", "en": "canned tomatoes",
        "family": "tomato", "aliases": ["can whole tomatoes",
        "whole peeled tomatoes", "canned whole tomatoes",
        "can crushed tomatoes", "chopped tomatoes", "crushed tomatoes",
        "gestückelte tomaten", "tomaten, geschält", "tomaten geschält",
        "dosen-tomaten"], "variant_of": "tomato_passata",
        "variant_note": "Ganze/stückige Dosen-tomaten statt püriert: kurz pürieren"},
    "tomato_paste": {"de": "Tomatenmark", "en": "tomato paste",
        "family": "tomato", "aliases": ["tomato paste", "tomatenmark"],
        "sibling_of": ["tomato_passata"],
        "sibling_note": "Tomatenmark ist konzentriert: deutlich sparsamer dosieren"},
    "tomatoes_dried": {"de": "Getrocknete Tomaten",
        "en": "dried tomatoes", "family": "tomato",
        "aliases": ["dried tomatoes", "getrocknete tomaten",
        "sun-dried tomatoes"]},
    "tomatoes_fresh": {"de": "Tomaten", "en": "tomatoes", "family": "produce",
        "aliases": ["tomatoes", "tomato", "tomaten", "cherry tomatoes",
        "roma tomatoes", "pomodorini", "punnet cherry tomatoes",
        "kirschtomaten"]},

    # --- canned & conserves ---------------------------------------------------------
    "coconut_milk": {"de": "Kokosmilch", "en": "coconut milk",
        "family": "dairy_alt",
        "aliases": ["coconut milk", "kokosmilch", "kókusztej",
        "coconut cream"]},
    "coconut_dried": {"de": "Kokosraspeln", "en": "desiccated coconut",
        "family": "baking", "aliases": ["desiccated coconut",
        "kokosraspeln", "coconut flakes", "shredded coconut"]},
    "chickpeas": {"de": "Kichererbsen", "en": "chickpeas",
        "family": "legume", "aliases": ["chickpeas", "chick peas",
        "chickpea", "kichererbsen", "can chickpeas", "ceci",
        "ceci sottovuoto", "garbanzo beans", "garbanzos"]},
    "lentils": {"de": "Linsen", "en": "lentils", "family": "legume",
        "aliases": ["lentils", "linsen", "red lentils", "beluga linsen",
        "braune linsen", "brown lentils", "grüne linsen"]},
    "beans_baked": {"de": "Bohnen Tomatensauce",
        "en": "baked beans", "family": "legume",
        "aliases": ["baked beans", "tomatbønner", "can black beans",
        "black beans", "bohnen in tomatensauce"]},
    "sweetcorn": {"de": "Zuckermais (Dose)", "en": "sweet corn",
        "family": "legume", "aliases": ["sweet corn", "sweetcorn",
        "gemüsemais", "junger gemüsemais", "corn kernels", "corn cob",
        "corn cobs", "maiskolben"]},
    "kimchi": {"de": "Kimchi", "en": "kimchi", "family": "pantry_conserve",
        "aliases": ["kimchi", "kimchi, korean made"]},
    "coffee": {"de": "Kaffee", "en": "coffee", "family": "drinks",
        "aliases": ["coffee", "coffee beans", "espresso", "espresso beans",
        "whole coffee beans", "espresso ganze bohne", "kaffee",
        "kaffeebohnen", "ganze kaffeebohnen", "instant coffee",
        "kaffeepulver", "filterkaffee", "decaffeinated coffee"]},
    "apple_sauce": {"de": "Apfelmus", "en": "apple sauce",
        "family": "pantry_conserve",
        "aliases": ["apple sauce", "applesauce", "apfelmus"]},
    "pesto": {"de": "Pesto", "en": "pesto", "family": "pantry_conserve",
        "aliases": ["pesto", "basil pesto", "pesto basilico"]},
    "vinegar_fruit": {"de": "Fruchtessig", "en": "fruit vinegar",
        "family": "vinegar", "aliases": ["fruit vinegar", "raspberry vinegar",
        "himbeer & essig", "himbeeressig"],
        "sibling_of": ["vinegar_apple", "vinegar_mild_white"]},
    "fried_onions": {"de": "Röstzwiebeln", "en": "fried onions",
        "family": "pantry_conserve", "aliases": ["fried onions",
        "röstzwiebeln", "crispy fried onions"]},
    "sauerkraut": {"de": "Sauerkraut", "en": "sauerkraut",
        "family": "pantry_conserve", "aliases": ["sauerkraut"]},

    # --- dairy, eggs, fats ------------------------------------------------------------
    "butter": {"de": "Butter", "en": "butter", "family": "dairy",
        "aliases": ["butter", "unsalted butter", "melted ghee"],
        "variant_note": "Für Ghee: Butter langsam klären oder direkt nehmen"},
    "ghee": {"de": "Ghee", "en": "ghee", "family": "dairy",
        "aliases": ["ghee", "butterschmalz"], "variant_of": "butter",
        "variant_note": "Butter statt Ghee: bei hoher Hitze bräunt sie — Geschmack passt trotzdem"},
    "milk": {"de": "Vollmilch", "en": "milk", "family": "dairy",
        "aliases": ["milk", "whole milk", "vollmilch", "milch"]},
    "buttermilk": {"de": "Buttermilch", "en": "buttermilk",
        "family": "dairy", "aliases": ["buttermilch", "buttermilk"]},
    "milk_oat": {"de": "Haferdrink", "en": "oat milk",
        "family": "dairy_alt", "aliases": ["oat milk", "oat drink",
        "hafermilch", "haferdrink", "barista drink hafer"]},
    "cream": {"de": "Sahne", "en": "thickened cream", "family": "dairy",
        "aliases": ["thickened cream", "heavy cream", "double cream",
        "whipping cream", "sahne", "schlagsahne", "single light cream",
        "light cream", "cooking cream", "single"]},
    "yogurt": {"de": "Joghurt", "en": "yogurt", "family": "dairy",
        "aliases": ["yogurt", "yoghurt", "greek yogurt", "greek yoghurt",
        "joghurt", "skyr"]},
    "eggs": {"de": "Eier", "en": "eggs", "family": "dairy",
        "aliases": ["eggs", "egg", "large eggs", "extra-large eggs",
        "egg yolks", "medium eggs", "eier", "ei", "eier (größe m)"]},
    "cheese_parmesan": {"de": "Parmesan", "en": "parmesan",
        "family": "cheese", "aliases": ["parmesan", "parmesan cheese",
        "parmigiano", "pecorino", "pecorino cheese", "grana padano"]},
    "cheese_gouda": {"de": "Gouda", "en": "cheddar", "family": "cheese",
        "aliases": ["cheddar cheese",
        "medium sharp cheddar cheese", "gouda", "red leicester cheese"]},
    "cheese_melt": {"de": "Raclettekäse", "en": "gruyere",
        "family": "cheese", "aliases": ["gruyere cheese", "gruyere",
        "raclette cheese", "emmentaler", "mozzarella", "ricotta",
        "fresh ricotta cheese", "feta"]},
    "stock_powder": {"de": "Brühe", "en": "stock", "family": "broth",
        "aliases": ["chicken stock", "beef stock", "vegetable stock",
        "stock cube", "bouillon", "brühe", "gemüsebrühe", "hühnerbrühe",
        "chicken broth", "fond"]},

    # --- condiments ----------------------------------------------------------------------
    "soy_sauce": {"de": "Sojasauce", "en": "soy sauce",
        "family": "condiment", "aliases": ["soy sauce", "sojasauce",
        "light soy sauce", "dark soy sauce"]},
    "fish_sauce": {"de": "Fischsauce", "en": "fish sauce",
        "family": "condiment", "aliases": ["fish sauce", "nam pla"]},
    "mirin": {"de": "Mirin", "en": "mirin", "family": "condiment",
        "aliases": ["mirin", "sweet cooking wine"]},
    "sake_cooking": {"de": "Sake", "en": "sake", "family": "condiment",
        "aliases": ["sake", "cooking sake", "japanese rice wine"]},
    "gochujang": {"de": "Gochujang", "en": "gochujang",
        "family": "condiment", "aliases": ["gochujang", "gochu jang"]},
    "miso": {"de": "Miso", "en": "miso paste", "family": "condiment",
        "aliases": ["miso", "miso paste", "white miso", "red miso"]},
    "mustard": {"de": "Senf", "en": "mustard", "family": "condiment",
        "aliases": ["mustard", "english mustard", "dijon mustard",
        "senf", "senf, mittelscharf", "mittelscharfer senf",
        "senf mittelscharf"]},
    "worcester": {"de": "Worcestershiresauce",
        "en": "worcestershire sauce", "family": "condiment",
        "aliases": ["worcestershire sauce", "worcestershire"]},
    "hot_sauce": {"de": "Tabasco", "en": "hot sauce",
        "family": "condiment", "aliases": ["hot sauce", "tabasco", "tabasco sauce",
        "sriracha", "sambal oelek", "harissa"]},
    "sweet_chili_sauce": {"de": "Sweet-Chili-Sauce",
        "en": "sweet chili sauce", "family": "condiment",
        "aliases": ["sweet chilli sauce", "sweet chili sauce"]},
    "mayonnaise": {"de": "Mayonnaise", "en": "mayonnaise",
        "family": "condiment", "aliases": ["mayonnaise", "mayo"]},
    "peanut_butter": {"de": "Erdnussbutter", "en": "peanut butter",
        "family": "spread", "aliases": ["peanut butter", "erdnussbutter",
        "crunchy peanut butter"]},
    "nut_spread_choc": {"de": "Nuss-Nougat-Creme",
        "en": "chocolate nut spread", "family": "spread",
        "aliases": ["nudossi", "nudossi ohne palmöl", "haselkuss",
        "chocolate nut spread", "ovomaltine crunchy cream",
        "ovomaltine crunchy"]},
    "tahini": {"de": "Tahin", "en": "tahini", "family": "spread",
        "aliases": ["tahini", "hulled tahini", "tahin", "tahin sesammus"]},
    "sesame_seeds": {"de": "Sesamsamen", "en": "sesame seeds",
        "family": "seed", "aliases": ["sesame seeds",
        "toasted sesame seeds", "sesamsamen", "sesam"]},
    "nuts_cashew": {"de": "Cashewkerne", "en": "cashews",
        "family": "nut", "aliases": ["cashews", "cashew nuts",
        "cashewkerne"]},
    "jam": {"de": "Marmelade", "en": "jam", "family": "spread",
        "aliases": ["jam", "marmelade", "fruchtaufstrich",
        "lingonberry jam", "wildpreiselbeeren"]},

    # --- aromatics & produce ---------------------------------------------------------------
    "garlic": {"de": "Knoblauch", "en": "garlic", "family": "aromatic",
        "aliases": ["garlic", "garlic cloves", "of garlic", "knoblauch",
        "knoblauchzehen"]},
    "garlic_paste": {"de": "Knoblauchpaste", "family": "condiment",
        "en": "garlic paste",
        "aliases": ["garlic paste", "knoblauchpaste"],
        "variant_of": "garlic",
        "variant_note": "Paste statt Zehen: ca. 1 TL je Zehe"},
    "ginger": {"de": "Ingwer", "en": "ginger", "family": "aromatic",
        "aliases": ["ginger", "fresh ginger", "ground ginger",
        "piece fresh ginger", "ingwer"]},
    "ginger_paste": {"de": "Ingwerpaste", "en": "ginger paste",
        "family": "condiment", "aliases": ["ginger paste", "ingwerpaste",
        "garlic ginger paste"], "variant_of": "ginger",
        "variant_note": "Paste statt frischer Wurzel: ca. 1 TL je Daumen"},
    "onion": {"de": "Zwiebeln", "en": "onion", "family": "produce",
        "aliases": ["onion", "onions", "yellow onion", "brown onion",
        "zwiebel", "zwiebeln", "stuffzwiebeln"]},
    "onion_red": {"de": "Rote Zwiebeln", "en": "red onion",
        "family": "produce", "aliases": ["red onion", "red onions",
        "rote zwiebel", "zwiebel, rot", "large red onions",
        "small red onion"], "sibling_of": ["onion"],
        "sibling_note": "Rote Zwiebel schärfer & farbintensiver — roh top, gekocht ok"},
    "spring_onion": {"de": "Frühlingszwiebeln",
        "en": "spring onions", "family": "produce",
        "aliases": ["spring onion", "spring onions",
        "frühlingszwiebeln", "scallions", "green onions"],
        "sibling_of": ["onion"],
        "sibling_note": "Zwiebel grasiger — Lauchnote fehlt etwas"},
    "shallot": {"de": "Schalotten", "en": "shallots", "family": "produce",
        "aliases": ["shallot", "shallots", "schalotte", "schalotten"],
        "sibling_of": ["onion"],
        "sibling_note": "Schalotte milder & süßer als Zwiebel"},
    "carrot": {"de": "Karotten", "en": "carrot", "family": "produce",
        "aliases": ["carrot", "carrots", "karotte", "karotten", "möhren"]},
    "celery": {"de": "Sellerie", "en": "celery", "family": "produce",
        "aliases": ["celery", "sellerie", "of celery", "staudensellerie"]},
    "potato": {"de": "Kartoffeln", "en": "potatoes", "family": "produce",
        "aliases": ["potatoes", "potato", "kartoffeln", "kartoffel"]},
    "spinach": {"de": "Blattspinat", "en": "baby spinach",
        "family": "produce", "aliases": ["baby spinach", "spinach",
        "blattspinat", "spinat", "swiss chard"]},
    "peas": {"de": "Erbsen", "en": "peas", "family": "produce",
        "aliases": ["peas", "erbsen", "erbsen mit möhren", "mangetouts",
        "sugar snap peas", "frozen peas"]},
    "bell_pepper": {"de": "Paprika (Gemüse)", "en": "capsicum",
        "family": "produce", "aliases": ["red capsicum", "capsicum",
        "bell pepper", "rote paprika", "paprika (gemüse)"]},
    "chili_fresh": {"de": "Chilischoten", "en": "green chillies",
        "family": "produce", "aliases": ["green chilli", "green chillies",
        "red chilli", "jalapeño", "jalapeno", "thai chili",
        "chilischoten"]},
    "lemon": {"de": "Zitrone", "en": "lemon", "family": "produce",
        "aliases": ["lemon", "lemons", "zitrone", "lemon wedges",
        "preserved lemon"]},
    "lemon_juice": {"de": "Zitronensaft", "en": "lemon juice",
        "family": "produce",
        "aliases": ["lemon juice", "zitronensaft", "juice of 1 lemon", "juice of 2 lemons",
        "juice of a lemon", "zest and juice of 1 lemon", "lemon zest"],
        "variant_of": "lemon",
        "variant_note": "Saft vom Vorrat statt frischer Zitrone (Schale fehlt dann)"},
    "lime": {"de": "Limette", "en": "lime", "family": "produce",
        "aliases": ["lime", "limes", "limette", "limetten"]},
    "lime_juice": {"de": "Limettensaft", "en": "lime juice",
        "family": "produce", "aliases": ["lime juice", "limettensaft",
        "juice of 1 lime", "juice of 2 limes"],
        "variant_of": "lime",
        "variant_note": "Saft vom Vorrat statt frischer Limette"},
    "apple": {"de": "Äpfel", "en": "apples", "family": "produce",
        "aliases": ["apple", "apples", "apfel", "äpfel"]},
    "banana": {"de": "Bananen", "en": "bananas", "family": "produce",
        "aliases": ["banana", "bananas", "banane", "bananen",
        "overripe bananas"]},
    "blueberries": {"de": "Blaubeeren", "en": "blueberries",
        "family": "produce", "aliases": ["blueberries",
        "frozen blueberries", "blaubeeren"]},
    "avocado": {"de": "Avocado", "en": "avocado", "family": "produce",
        "aliases": ["avocado", "firm avocado"]},
    "bread_rolls": {"de": "Brötchen", "en": "ciabatta rolls",
        "family": "baking", "aliases": ["ciabatta rolls", "ciabatta",
        "brötchen", "brot"]},

    # --- baking ----------------------------------------------------------------------------
    "breadcrumbs": {"de": "Paniermehl", "en": "breadcrumbs",
        "family": "baking", "aliases": ["breadcrumbs",
        "dried breadcrumbs", "panko breadcrumbs", "panko",
        "samlip breadcrumbs panko", "bread crumbs"]},
    "yeast": {"de": "Hefe", "en": "yeast", "family": "baking",
        "aliases": ["yeast", "instant yeast", "dry yeast", "fresh yeast",
        "hefe", "backhefe", "trockenhefe"]},
    "baking_powder": {"de": "Backpulver", "en": "baking powder",
        "family": "baking", "aliases": ["baking powder", "backpulver"]},
    "baking_soda": {"de": "Natron", "en": "bicarbonate of soda",
        "family": "baking", "aliases": ["bicarbonate of soda",
        "bicarb soda", "baking soda", "natron",
        "gebackenes backpulver"]},
    "vanilla_extract": {"de": "Vanille-Extrakt", "en": "vanilla extract",
        "family": "baking", "aliases": ["vanilla extract",
        "vanilla essence", "vanilleextrakt"]},
    "chocolate_dark": {"de": "Zartbitterschokolade",
        "en": "dark chocolate", "family": "baking",
        "aliases": ["dark chocolate", "dark chocolate chips",
        "chocolate chips", "kuvertüre", "zartbitterschokolade"]},
    "cocoa": {"de": "Kakaopulver", "en": "cocoa powder",
        "family": "baking", "aliases": ["cocoa powder", "cocoa",
        "kakaopulver"]},
    "ice_cream": {"de": "Vanilleeis", "en": "ice cream",
        "family": "frozen", "aliases": ["ice cream", "vanilla ice cream",
        "vanilleeis"]},

    # --- water, wraps, misc ----------------------------------------------------------
    "water": {"de": "Wasser", "en": "water", "family": "staple",
        "aliases": ["water", "wasser", "boiling water", "hot water",
        "warm water", "cold water", "heißes wasser", "kaltes wasser",
        "lauwarmes wasser", "kochendes wasser", "of water"]},
    "eggplant": {"de": "Auberginen", "en": "eggplant", "family": "produce",
        "aliases": ["eggplant", "eggplants", "large eggplant",
        "large eggplants", "aubergine", "auberginen"]},
    "pine_nuts": {"de": "Pinienkerne", "en": "pine nuts", "family": "nut",
        "aliases": ["pine nuts", "toasted pine nuts", "pinienkerne"]},
    "pecans": {"de": "Pekannüsse", "en": "pecans", "family": "nut",
        "aliases": ["pecans", "pecan nuts", "pekannüsse"]},
    "cooking_wine": {"de": "Kochwein", "en": "cooking wine",
        "family": "condiment", "aliases": ["red wine", "white wine",
        "cooking wine", "kochwein", "rotwein"]},
    "wheat_gluten": {"de": "Weizengluten", "en": "vital wheat gluten",
        "family": "baking", "aliases": ["vital wheat gluten",
        "wheat gluten", "weizengluten"]},
    "rice_paper": {"de": "Reispapier", "en": "rice paper",
        "family": "pantry_conserve", "aliases": ["rice paper",
        "reispapier für frühlingsröllchen", "reispapier"]},
    "tortillas": {"de": "Tortillas", "en": "tortillas",
        "family": "pantry_conserve", "aliases": ["tortillas",
        "white corn tortillas", "flour tortillas", "weizentortillas",
        "oz yufka weizentortillas"], "sibling_of": ["naan"]},
    "naan": {"de": "Naan", "en": "naan", "family": "pantry_conserve",
        "aliases": ["naan", "naan bread"]},
    "saffron": {"de": "Safran", "en": "saffron", "family": "spice",
        "aliases": ["saffron", "saffron threads", "safran",
        "safran fäden"]},
    "chicken": {"de": "Hähnchen", "en": "chicken", "family": "meat",
        "aliases": ["chicken", "chicken breasts", "chicken thighs",
        "chicken thigh fillets", "raw chicken frames",
        "chicken carcass", "hähnchen", "hähnchenbrust"]},
    "pork_belly": {"de": "Schweinebauch", "en": "pork belly",
        "family": "meat", "aliases": ["pork belly", "schweinebauch"]},
    "mince": {"de": "Hackfleisch", "en": "mince", "family": "meat",
        "aliases": ["beef mince", "pork mince", "hackfleisch", "rinderhack"]},
    "sausages": {"de": "Bratwurst", "en": "sausages", "family": "meat",
        "aliases": ["thick italian pork sausages", "chorizo sausages",
        "sausages", "bratwurst", "chorizo", "pancetta", "bacon",
        "guanciale"]},
    "lamb": {"de": "Lamm", "en": "lamb", "family": "meat",
        "aliases": ["lamb hind shanks", "lamb shanks", "lamb",
        "cooked lamb", "lamm"]},
}

# ---------------------------------------------------------------------
# Blends: key -> component concept keys. A stocked blend satisfies
# recipes calling for a component (in_blend tier); a missing blend with
# >=50% stocked components yields a "mix it yourself" suggestion.
# ---------------------------------------------------------------------
BLENDS: dict[str, list[str]] = {
    "five_spice": ["fennel_seeds", "cinnamon", "star_anise", "cloves",
                   "szechuan_pepper"],
    "garam_masala": ["coriander_seed", "cumin", "cardamom", "cloves",
                     "black_pepper", "cinnamon"],
    "curry_powder": ["turmeric", "coriander_seed", "cumin", "fenugreek_seed",
                     "chili_ground"],
    "italian_herbs": ["oregano", "basil_dried", "thyme", "rosemary"],
    "cajun": ["paprika_sweet", "chili_ground", "garlic", "onion",
              "black_pepper"],
    "brotgewuerz": ["coriander_seed", "fennel_seeds", "caraway"],
    "lemon_pepper_mix": ["black_pepper", "lemon_juice"],
}

# Kitchen-shelf categories: spices get their own chip; baking goods
# (flours, starch, leavening) cluster; drinks stays drinkables only.
FAMILY_DEFAULT_CATEGORY = {
    "spice": "Spices", "blend": "Spices", "herb_dried": "Spices",
    "herb_fresh": "Produce", "oil": "Pantry", "vinegar": "Pantry",
    "sugar": "Pantry", "flour": "Baking", "grain": "Pantry",
    "starch": "Baking", "pasta": "Pantry", "tomato": "Pantry",
    "legume": "Pantry", "produce": "Produce", "aromatic": "Produce",
    "dairy": "Dairy", "dairy_alt": "Pantry", "cheese": "Dairy",
    "egg": "Dairy", "broth": "Pantry", "condiment": "Pantry",
    "pantry_conserve": "Pantry", "baking": "Baking", "nut": "Pantry",
    "seed": "Pantry", "spread": "Pantry", "frozen": "Pantry",
    "staple": "Pantry", "meat": "Meat", "drinks": "Drinks",
}

# Fuzzy fallback must never bridge these concept keys (lookalike traps).
NEVER_FUZZY_PAIRS = {
    frozenset({"caraway", "cumin"}),
    frozenset({"parsley", "coriander_seed"}),
    frozenset({"black_pepper", "white_pepper"}),
    frozenset({"tomato_paste", "tomato_passata"}),
}

# -------------------------------------------------------------------------
# Junk classification — lines that are not pantry items at all
# -------------------------------------------------------------------------
EQUIPMENT_WORDS = (
    "spätzlepresse", "spätzlehobel", "schaumlöffel", "pfanne", "topf",
    "schüssel", "küchenmaschine", "nudelmaschine", "backblech",
    "backpapier", "alufolie", "brotform", "kastenform", "springform",
    "auflaufform", "nudelholz", "dämpfer", "wasserkocher", "topflappen",
    "teigschaber", "schaber", "pizzaschneider", "steamer", "zuschneider",
    "mittelscharfes messer", "hitzebeständige handschuhe", "form (20 cm)",
    "durchschnittsschaber", "silikonmatte", "beschichtete",
)
NOISE_NAMES = {
    "produkte", "produkt", "minuten", "minute", "std", "stunde",
    "stunden", "personen", "portionen", "kalorien", "kcal",
    "zubereitung", "nährwerte", "anleitung", "instruction", "notes",
    "zutaten", "ingredients", "dauer", "zeit", "kategorie", "kategorien",
    "tags", "druck", "kommentar", "kommentare", "pin it", "tweet",
    "share", "bookmark", "yield", "servings", "prep time", "cook time",
    "total time", "cuisine", "autor", "single", "packet", "packets",
    "pkt", "tin", "tins", "can", "cans", "bunch", "punnet", "splash",
    "pinch", "divided", "sworth",
}
PREPARED_REF_RE = re.compile(
    r"(\bfrom earlier\b|\bsee my\b|\bsee recipe\b|\bsee below\b|"
    r"\bleftover|\bthe marinade\b|\bcooked rice\b|\bsteamed basmati rice\b|"
    r"\bwarm milk with a pinch\b|^cooked \w+$|^steamed \w+$)",
    re.IGNORECASE)

WATER_QUALIFIERS = re.compile(
    r"^(?:boiling|hot|warm|cold|room temperature|lauwarm(?:es)?|"
    r"heiß(?:es)?|kalt(?:es)?|eiskalt(?:es)?|sprudelnd(?:es)?|stilles)\s+",
    re.IGNORECASE)


def _norm(text: str) -> str:
    text = (text or "").strip().lower()
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"['\u2018\u2019]", "", text)
    return re.sub(r"\s+", " ", text).strip()


# alias -> concept key (built once; first alias wins on collisions, so
# seed order matters — more specific concepts come first above)
ALIASES: dict[str, str] = {}
for _key, _c in CONCEPTS.items():
    for _alias in _c.get("aliases", []):
        _a = _norm(_alias)
        if _a and _a not in ALIASES:
            ALIASES[_a] = _key

# long aliases usable for containment scans (item names carry brand noise)
_CONTAINMENT: dict[str, str] = {}
for _a, _k in ALIASES.items():
    if len(_a) >= 8:
        _CONTAINMENT.setdefault(_a, _k)


def _rel_map(kind: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, c in CONCEPTS.items():
        if kind == "variant_of" and c.get("variant_of"):
            out.setdefault(key, []).append(c["variant_of"])
        elif kind == "sibling_of":
            for s in c.get("sibling_of") or []:
                out.setdefault(key, []).append(s)
                out.setdefault(s, []).append(key)
    return out


VARIANTS = _rel_map("variant_of")
SIBLINGS = _rel_map("sibling_of")
IN_BLEND: dict[str, list[str]] = {}
for _blend, _parts in BLENDS.items():
    for _p in _parts:
        IN_BLEND.setdefault(_p, []).append(_blend)

_GENERIC_VARIANT_NOTE = "Andere Form im Vorrat — Menge grob anpassen"
_GENERIC_SIBLING_NOTE = "Nächste Verwandte im Vorrat — Aroma weicht etwas ab"


def _note(concept: str, blend: str | None, kind: str) -> str:
    c = CONCEPTS.get(blend or concept, {})
    note = c.get(f"{kind}_note")
    return note or (_GENERIC_SIBLING_NOTE if kind == "sibling" else
                    _GENERIC_VARIANT_NOTE if kind == "variant" else "")


def resolve(name: str) -> tuple[str | None, str]:
    """Ingredient item name -> (concept key or None, normalized name).

    Final deterministic normalization the import pipeline doesn't do:
    serving/taste tails, dangling punctuation, "(...)" metadata blocks,
    "X of Y" leftovers, water temperature adjectives, comma tails and
    containment against long aliases (for lines the parser could only
    half-clean).
    """
    text = _norm(name)
    text = re.sub(r"^(?:etwas|ein wenig|some|a little)\s+", "", text)
    text = re.sub(r"^of\s+", "", text)
    text = re.sub(
        r",?\s*(?:to taste|to season|to serve|to garnish|for garnish|"
        r"zum servieren|nach geschmack|als beilage|to accompany|"
        r"as needed|nach bedarf|see my recipe)\b.*$", "", text)
    text = re.sub(
        r"\s+for\s+(?:shallow\s+|deep\s+)?(?:frying|baking|greasing)"
        r".*$", "", text)
    text = re.sub(r"\s+für\s+(?:die\s+)?form(?:en)?(?:\s.*)?$", "", text)
    text = re.sub(r"\s+zum\s+(?:einfetten|ausfetten|bestreichen).*$", "", text)
    text = re.sub(r" and zest$", "", text)
    text = re.sub(r"^zest and juice of", "juice of", text)
    text = re.sub(r"^[\s\-–—(]+|[\s\-––,;:.)\\/+]+$", "", text).strip()
    text = re.sub(r"\(\s*\)", "", text)
    if text in ALIASES:
        return ALIASES[text], text
    # balanced and unbalanced paren tails: "(Größe M", "(approx 1kg/2.2lbs)"
    inner = re.sub(r"\([^)]*\)?", " ", text)
    inner = re.sub(r"\s+", " ", inner).strip(" -–—,;:.")
    for cand in (inner, text):
        if cand in ALIASES:
            return ALIASES[cand], cand
    # "3 cloves of garlic" / "thumb-sized piece of fresh ginger"
    m = re.match(r"^(.{1,25}?)\s+of\s+(\S.*)$", inner)
    if m:
        tail = m.group(2).strip()
        if tail in ALIASES:
            return ALIASES[tail], tail
        if len(tail) > 2:
            sub = resolve(tail)
            if sub[0]:
                return sub
    for sep in (",", "/", "|"):
        if sep in inner:
            head = inner.split(sep, 1)[0].strip()
            if head and len(head) >= 3:
                r = resolve(head)
                if r[0]:
                    return r
    dash = re.split(r"\s+[-–]\s+", inner, 1)[0].strip()
    if dash and dash != inner and len(dash) >= 3:
        r = resolve(dash)
        if r[0]:
            return r
    # "Butter and honey" -> "Butter" when the stem resolves
    m = re.match(r"^(.+?)\s+and\s+\S+$", inner)
    if m and len(m.group(1)) >= 3:
        r = resolve(m.group(1))
        if r[0]:
            return r
    if len(inner) >= 8:  # containment: longest matching alias wins
        best, best_key = "", None
        for alias, key in _CONTAINMENT.items():
            if alias in inner and len(alias) > len(best):
                best, best_key = alias, key
        if best_key:
            return best_key, inner
    pieces = re.findall(r"\(([^)]{3,40})\)", text)
    tail = re.search(r"\(([^)]{3,40})$", text)
    if tail and tail.group(1) not in pieces:
        pieces.append(tail.group(1))
    for piece in pieces:
        sub = resolve(piece)
        if sub[0]:
            return sub
    water = WATER_QUALIFIERS.sub("", inner).strip()
    if water != inner and water in ALIASES:
        return ALIASES[water], water
    return None, text


def search_concepts(query: str, limit: int = 8) -> list[dict]:
    """Autocomplete for the tag picker: concepts whose label or alias
    contains the typed text. Prefix hits come first — labels before
    aliases — then substring hits; the shortest match wins within each
    tier, so "zimt" surfaces Zimt before Zimtstangen."""
    q = _norm(query)
    if not q:
        return []
    best: dict[str, tuple[int, int, str]] = {}  # concept -> (tier, len, matched)
    for cid, concept in CONCEPTS.items():
        variants = [concept["de"], concept["en"], *concept.get("aliases", [])]
        for text in variants:
            n = _norm(text)
            if not n:
                continue
            if n == q or n.startswith(q):
                is_label = text in (concept["de"], concept["en"])
                key = (0 if is_label else 1, len(n), n)
            elif q in n:
                key = (2, len(n), n)
            else:
                continue
            if cid not in best or key < best[cid]:
                best[cid] = key
    ranked = sorted(best.items(), key=lambda kv: kv[1])[:limit]
    out = []
    for cid, (_, _, matched) in ranked:
        meta = CONCEPTS[cid]
        alias = matched if matched not in (_norm(meta["de"]), _norm(meta["en"])) else None
        out.append({"concept_id": cid, "label": meta["de"], "alias": alias})
    return out


def resolve_item_concept(item) -> str | None:
    """Inventory item dict -> concept key via aliases (exact, then
    guarded containment). Branded suffixed names ("Bio Natives Olivenöl
    Extra", "Natives Olivenöl Bio") still resolve — but a mid-name hit
    after "mit ..." never tags ("Erasco Käse-Lauch-Suppe mit Hackfleisch"
    is a soup, not mince)."""
    name = _norm((item or {}).get("name") or "")
    if not name:
        return None
    if name in ALIASES:
        return ALIASES[name]
    best, best_key = 0.0, None
    for alias, key in _CONTAINMENT.items():
        pos = name.find(alias)
        if pos < 0:
            continue
        at_start = pos == 0
        if pos > 0 and name[max(0, pos - 4):pos].rstrip().endswith("mit"):
            continue  # "suppe mit Hackfleisch" & friends: ingredient list, not the food
        if not at_start and len(alias) < 12:
            continue  # mid-name hits need a long, specific alias
        score = len(alias) / len(name) * (1.2 if at_start else 1.0)
        if score > best:
            best, best_key = score, key
    return best_key if best > 0.30 else None


def stock_map(items) -> dict[str, list[dict]]:
    """concept -> stocked items (best first: quantity>0, shorter name)."""
    out: dict[str, list[dict]] = {}
    for item in items or []:
        concept = resolve_item_concept(item)
        if concept:
            out.setdefault(concept, []).append(item)
    for concept, entries in out.items():
        entries.sort(key=lambda i: (i.get("quantity", 0) <= 0,
                                    len(i["name"])))
    return out


def junk_class(name) -> str | None:
    """'equipment' | 'noise' | None. These lines must never be matched,
    shopped or deducted."""
    text = _norm(name)
    if not text:
        return "noise"
    if text in NOISE_NAMES:
        return "noise"
    if re.fullmatch(r"\d*(?:[.,]\d+)?\s*(minuten|std|stunden)", text):
        return "noise"
    if any(word in text for word in EQUIPMENT_WORDS):
        return "equipment"
    return None


def is_prepared_reference(raw: str, name: str) -> bool:
    hay = f"{raw or ''} {name or ''}".lower()
    return bool(PREPARED_REF_RE.search(hay))


def resolve_for_stock(name: str, items, stocked: dict | None = None) -> dict:
    """Full ranked cascade for one cleaned ingredient name against the
    live item list. Result (never raises):
      concept, cleaned, kind, item_id, item_name, note, buy_name
    kind: identity|variant|in_blend|sibling|components|buy|staple|unknown
    STOCKED is an optional precomputed stock_map(items) — pass it when
    resolving many names against the same item list.
    """
    concept, cleaned = resolve(name)
    result = {"concept": concept, "cleaned": cleaned, "kind": "unknown",
              "item_id": None, "item_name": None, "note": "",
              "buy_name": None}
    if not concept:
        return result
    meta = CONCEPTS[concept]
    result["buy_name"] = meta["de"]
    if concept == "water":
        result["kind"] = "staple"
        return result
    if stocked is None:
        stocked = stock_map(items)

    def _pick(entries):
        return entries[0] if entries else None

    def _set(kind, item, note=""):
        result.update(kind=kind, item_id=item["id"], item_name=item["name"],
                      note=note)

    def _ingredient_family(key):
        return CONCEPTS.get(key, {}).get("family")

    same = stocked.get(concept) or []
    if same:
        # same concept, but the stocked form may want a usage note
        # ("Kardamom Saat" for ground cardamom)
        note = meta.get("variant_note") or ""
        _set("identity", _pick(same), note)
        return result
    for variant in VARIANTS.get(concept, []):
        entries = stocked.get(variant)
        if entries:
            _set("variant", _pick(entries), _note(concept, variant, "variant"))
            return result
    # blends only cover spice/herb components: garlic being *in* the Cajun
    # mix doesn't make it available — a recipe's garlic is fresh garlic
    if _ingredient_family(concept) in ("spice", "herb_dried"):
        for blend in IN_BLEND.get(concept, []):
            entries = stocked.get(blend)
            if entries:
                label = CONCEPTS[concept]["de"]
                _set("in_blend", _pick(entries),
                     f"{label} steckt in {entries[0]['name']}")
                return result
    for sibling in SIBLINGS.get(concept, []):
        entries = stocked.get(sibling)
        if entries:
            _set("sibling", _pick(entries), _note(concept, sibling, "sibling"))
            return result
    parts = BLENDS.get(concept) or []
    if parts:
        have = [p for p in parts if stocked.get(p)]
        if have and len(have) / len(parts) >= 0.5:
            missing = [CONCEPTS[p]["de"] for p in parts if not stocked.get(p)]
            note = ("Selbst mischen aus: "
                    + ", ".join(CONCEPTS[p]["de"] for p in have))
            if missing:
                note += " (fehlt noch: " + ", ".join(missing) + ")"
            result["kind"] = "components"
            result["note"] = note
            return result
    result["kind"] = "buy"
    return result
