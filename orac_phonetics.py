#---------------------------------------------------#
#     ORAC-VOICE v1.0.2 (Lore friendly VoiceChat)	#
#          Copyright © 2026 Caroline Mayne			#
#		   https://github.com/CarolinaJones/	   	#
#––––––––––––––––––––––––––––––––––––––––––––-----––#

import re

def _preserve_case(match, replacement):
    """Preserves the original capitalization of the matched word."""
    original_word = match.group()
    if original_word.istitle():
        return replacement.capitalize()
    elif original_word.isupper():
        return replacement.upper()
    return replacement

def orac_phonetics(text):
    corrections = {
        # === Blake's 7 Specifics ===
        r"\bAI\b": "Artificial Intelligence",
        r"\bAvon\b": "Avon",
        r"\bDSV-1\b": "D. S. Vee ONE", r"\bDSV-2\b": "D. S. Vee TWO",
        r"\bGan\b": "Gann",
        r"\bGrant\b": "Grarnt", r"\bgranting\b": "grarnting",
        r"\bLaseron\b": "laze'ron", r"\bLasters\b": "blarsters",
        r"\bMutoid\b": "Mew-toid", r"\bMutoids\b": "Mew-toids",
        r"\bORAC\b": "Oarack",
        r"\bServalan\b": "Serva'lan'n",
        r"\bsoma\b": "so'mah",
        r"\btarial\b": "tah'ree'el",
        r"\bVila\b": "Villa",
        r"\bZen\b": "Zenn",
        
        # === Technical & Mechanical ===
        r"\badvanced\b": "advarnsed", r"\badvancing\b": "advarnsing",
        r"\bcircuitry\b": "sur-kit-tree",
        r"\bcomputer\b": "com'pute'r", r"\bsupercomputer\b": "supah com'pute'r",
        r"\bcontinued\b": "contin'ewed", r"\bcontinues\b": "contin'ews",
        r"\bdata\b": "day'tah", r"\bdatabanks\b": "day'tah banks", r"\bdatasets\b": "day'tah sets",
        r"\bdefenses\b": "d'fences",
        r"\bdiversion\b": "die-version",
        r"\bEMP\b": "E.M.P", r"\bexoplanet\b": "Exo'planet",
        r"\bfacade\b": "fas'arde",
        r"\bimplants\b": "implarnts",
        r"\bprocess\b": "pro-cess", r"\bprocesses\b": "pro'sesses", r"\bprocessing\b": "proe'cesssing", r"\bprocessors\b": "proe'sessors",
        r"\bprogress\b": "proe'gress",
        r"\bstatus\b": "staytus",
        r"\bsurpasses\b": "sur'parsses", r"\bsurpassing\b": "surr-parssing", r"\bsurpassed\b": "sur'parssed",
        r"\btransmitter\b": "transmit'a",
        r"\bweaponize\b": "wepponise",

        # === The 'A' to 'AR' (Trap-Bath Split) ===
        r"\bafter\b": "arfter", r"\baftermath\b": "arfter-math",
        r"\banswer\b": "arn'sser", r"\banswers\b": "arn'ssers", r"\banswering\b": "arn'ssering",
        r"\bask\b": "arsk", r"\basking\b": "arsking", r"\basks\b": "arsks",
        r"\bblast\b": "blarst", r"\bblasted\b": "blarsted", r"\bblasting\b": "blarsting",
        r"\bbranch\b": "brarnch", r"\bbranches\b": "brarnches",
        r"\bbrass\b": "brarrss", r"\bbypass\b": "byparrse", r"\bbypassing\b": "bye-parss'sing",
        r"\bcan't\b": "carnt", r"\bcannot\b": "can-not", 
        r"\bcast\b": "karst", r"\bcasting\b": "karsting",
        r"\bcastle\b": "kar-sel",
        r"\bchance\b": "charnce", 
        r"\bchant\b": "charnt",
        r"\bclass\b": "clarss", 
        r"\bclasp\b": "klarsp", r"\bclasped\b": "klarsped",
        r"\bcommand\b": "commarnd", r"\bcommander\b": "commarnder", r"\bcommanded\b": "commarnded",
        r"\bcontrast\b": "contrarst", r"\bcontrasting\b": "contrarsting",
        r"\bcraft\b": "krarft", r"\bcrafted\b": "krarfted", r"\bcrafting\b": "krarfting", r"\bcraftstman\b": "crarftsman",
        r"\bdance\b": "darnce",
        r"\bdemand\b": "d'marnd", r"\bdemanding\b": "d'marnding", r"\bdemands\b": "d'marnds", r"\bdemanded\b": "d'marnded",
        r"\benhance\b": "enharnse", r"\benhanced\b": "enharnsed", r"\benhancing\b": "enharnsing",
        r"\bexample\b": "exarmple", r"\bexamples\b": "exarmples",
        r"\bfast\b": "farst", r"\bfaster\b": "farster", r"\bfastest\b": "farstest",
        r"\bglass\b": "glarss",
        r"\bgraft\b": "grarft", r"\bgrafted\b": "grarfted",
        r"\bgrasp\b": "grarsp", r"\bgrasps\b": "grarsps", r"\bgrasped\b": "grarsped", r"\bgrasping\b": "grarsping",
        r"\bgrass\b": "grarrss",
        r"\bhalf\b": "harf", r"\bhalves\b": "harves",
        r"\bimplant\b": "implarnt", r"\bneural-implant\b": "nu'ral im'plarnt", r"\bimplanted\b": "implarnted",
        r"\blast\b": "larst", r"\blasted\b": "larsted", r"\blasting\b": "larsting", r"\blastly\b": "larstly",
        r"\blaugh\b": "larf", r"\blaughing\b": "larfing", r"\blaughter\b": "larf-tah",
        r"\bmask\b": "marsk", r"\bmasked\b": "marsked", r"\bmasking\b": "marsking",
        r"\bmaster\b": "marster", r"\bmastery\b": "marstery",
        r"\bnasty\b": "narsty",
        r"\bpass\b": "parss", r"\bpassable\b": "parssable", r"\bpassed\b": "parssed",
        r"\bpast\b": "parst", r"\bpaths\b": "parths", r"\bpathways\b": "parth-ways",
        r"\bplant\b": "plarnt", r"\bplanted\b": "plarnted",
        r"\brelay\b": "ree'lay",
        r"\bsample\b": "sarmpel", r"\bsamples\b": "sarmpels",
        r"\bshaft\b": "sharft", r"\bshafts\b": "sharfts",
        r"\bslant\b": "slarnt",
        r"\bstance\b": "starnce",
        r"\btakeover\b": "tayk-over",
        r"\btask\b": "tarsk", r"\btasked\b": "tarsked", r"\btasks\b": "tarsks", r"\btasking\b": "tarsking",
        r"\bvast\b": "varst", r"\bvastly\b": "varstly",

        # === General British Phonetics ===
        r"\badvancement\b": "advarncement", r"\badvantage\b": "ad'varntage",
        r"\baluminum\b": "al-yoo-min'ee'um",
        r"\banti\b": "an-tee", r"\articulate\b": "artic-ul'ate",
        r"\bconstruct\b": "conn-struct",
        r"\bexile\b": "ex'ile", r"\bexiled\b": "exx'iled",
        r"\belaborate\b": "elabor'rate",
        r"\bflawed\b": "floored",
        r"\bfutile\b": "few-tile", r"\bhostile\b": "hos-tile",
        r"\bleisure\b": "lezh'yah",
        r"\bmulti\b": "mul-tee",
        r"\bonly\b": "own-lee",
        r"\bpresent\b": "pressant",
        r"\bprivacy\b": "pry-va'see",
        r"\brather\b": "rarther",
        r"\broute\b": "root",
        r"\bsatisifed\b": "satisfied",
        r"\bschedule\b": "shed-yool",
        r"\btraverse\b": "tre'verss", r"\btraverses\b": "trah'verss'es", r"\btraversing\b": "tre'verssing",
        r"\bvia\b": "vy'ah",
        r"\byour\b": "yor",
        
        # === ORAC Attitude & High Status ===
        r"\berror\b": "air-rah",
        r"\bfutility\b": "futilit'ee",
        r"\billogical\b": "ill'loji'kol",
        r"\bI've\b": "I have", r"\bI'll\b": "I will",
        r"\binquiry\b": "in-kwirey", r"\binquiries\b": "in-kwireys",
        r"\bkindergarten-level\b": "childish", r"\bkindergarten levels\b": "mediocre levels",
        
        # === MORE Contractions ===
        r"\bdon't\b": "do not", r"\bwon't\b": "will not", r"\byou're\b": "you are", r"\bit's\b": "it is", r"\bwe're\b": "we are", r"\bthey're\b": "they are",
    }
   
    for pattern, phonetic in corrections.items():
        text = re.sub(
            pattern, 
            # ADD p=phonetic HERE to prevent the Python lambda loop bug!
            lambda match, p=phonetic: _preserve_case(match, p), 
            text, 
            flags=re.IGNORECASE
        )
    return text