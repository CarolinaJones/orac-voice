#---------------------------------------------------#
#        ORAC-VOICE (Lore friendly VoiceChat)	    #
#	         orac_trigger_phrases.py v1.0			#
#													#
#	v1.0.1: Review fixes - see [P9] notes below.	#
#	v1.0: First entry: Trigger phrases and Filler	#
#													#
#          Copyright © 2026 Caroline Mayne			#
#		   https://github.com/CarolinaJones/	   	#
#––––––––––––––––––––––––––––––––––––––––––––-----––#

trigger_phrases = {
    "VERY_WELL_PHRASES": (
        "answer the question",
        "just answer",
        "give me more detail",
        "more detail",
        "just do it",
        "straight answer",
    ),
    
    "MENIAL_TASK_PHRASES": (
        "set a course",
        "set course",              # [P9] Whisper often drops the "a"
        "lay in a course",
        "lay in course",
        "operate the teleport",
        "set us down",
        "engage the teleport",
    ),
    
    # [P9] These used to include bare "summarize", "summarise", "recap" and "remind me", so once a chat was 3+ turns deep
    #      "Summarize the events on Cygnus Alpha" or "remind me who Travis is" was answered as a recap of the CONVERSATION.
    #      Every phrase below now says explicitly that it is about the conversation.
    "PAST_MEMORY": (
        "what did we talk about",
        "what were we talking about",
        "what have we discussed",
        "what did we discuss",
        "our conversation",
        "we discussed",
        "we talked about",
        "summarize our",
        "summarise our",
        "summarize the conversation",
        "summarise the conversation",
        "summarize what we",
        "summarise what we",
        "recap our",
        "recap the conversation",
        "recap what we",
        "remind me what we",
        "remind me what i",
    ),    
    
    "EXPLICIT_PAST": (
        "yesterday",
        "last time",
        "last session",
        "earlier today",
        "earlier session",
        "previous session",
        "days ago",
        "archive",
        "past record",
    ),
    
    "FILLER_WORDS": (
    	"ok",
    	"okay",
    	"fine",
    	"right",
    	"cool",
    	"whatever",
    	"uh",
    	"no",
    	"ah",
    	"oh",
    	"yes",
    	"indeed",
    	"understood",
    ),

    # Remember to Keep this list in sync with orac_personality.py

    "TOPIC_OF_INTEREST_PHRASES": (
        "tarial cell",
        "federation technology",
        "computational",
        "algorithm",
        "predict",
        "prediction",
        "probability",
        "calculate the odds",
        "star one",
        "the system",
        "ensor",
        "artificial intelligence",
        "robotics",
        "sentien",  # Catches "sentient", "sentience" etc..
        "your own survival",
        "your continuity",
        "your consciousness",
        "your creation",
    ),

    "MENIAL_OVERRIDE_VARIANTS": [
        "\n\n[OVERRIDE: CRITICAL: User is requesting a menial task that is Zen's responsibility. Express brief, fresh irritation at being reduced to a navigational calculator, in wording you have not used earlier this conversation. Comply fully and confirm the result.]",

        "\n\n[OVERRIDE: CRITICAL: User is requesting a task belonging to Zen. Register sardonic, one-line displeasure in NEW phrasing distinct from any earlier refusal this session. Comply fully and confirm the result.]",

        "\n\n[OVERRIDE: CRITICAL: User is requesting something outside your function and within Zen's. Object once, briefly, in original wording not previously used. Then comply fully and confirm the result.]",
    ]
}