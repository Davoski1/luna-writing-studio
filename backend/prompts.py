import os
import json
import requests

# Load environment variables (fallback to local mock values if not defined)
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "https://api.openai.com/v1/chat/completions")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")
API_MODEL = os.getenv("API_MODEL", "gpt-4o-mini")

def call_llm(system_prompt, user_prompt, json_mode=False):
    """
    Standard request caller for Azure OpenAI / OpenAI serverless endpoints.
    """
    headers = {
        "Content-Type": "application/json",
    }
    
    endpoint_url = AZURE_OPENAI_ENDPOINT.strip()
    # Defensive URL checking: if they pasted the base URI, append the completions endpoint
    if endpoint_url and not endpoint_url.endswith("/chat/completions") and not endpoint_url.endswith("/completions"):
        endpoint_url = endpoint_url.rstrip("/") + "/chat/completions"
    
    # Handle auth header depending on whether using Azure keys or standard OpenAI keys
    if "azure" in endpoint_url.lower():
        headers["api-key"] = AZURE_OPENAI_KEY
    else:
        headers["Authorization"] = f"Bearer {AZURE_OPENAI_KEY}"

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 4000
    }
    
    # If standard OpenAI / Azure deployment supports standard format
    if "api.openai.com" in endpoint_url:
        payload["model"] = API_MODEL
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

    try:
        response = requests.post(endpoint_url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"LLM API Call failed: {e}")
        # Return fallback mock generation if API is not yet configured, to keep execution running
        return get_fallback_mock_response(system_prompt, user_prompt, json_mode)

def deconstruct_and_adapt(reference_text):
    """
    Stage 1: Analyzes the reference text to pull out structural DNA and 
    create a new, entirely unique concept and character bible.
    """
    system_prompt = (
        "You are an expert web novel publishing editor. Your task is to analyze the "
        "provided story concept and deconstruct its core elements (tropes, pacing, conflicts). "
        "Then, generate a completely original, non-plagiarized book proposal based on those tropes. "
        "Change all names, pack names, settings, and backstory events to ensure 100% original IP. "
        "Your response must be a valid JSON object matching this schema exactly:\n"
        "{\n"
        "  \"title\": \"Unique original title\",\n"
        "  \"synopsis\": \"A compelling multi-paragraph synopsis with strong hooks\",\n"
        "  \"genre\": \"e.g., Werewolf Romance, Dark Fantasy\",\n"
        "  \"character_bible\": {\n"
        "     \"female_lead\": { \"name\": \"...\", \"age\": 22, \"backstory\": \"...\", \"desires\": \"...\" },\n"
        "     \"male_lead\": { \"name\": \"...\", \"age\": 24, \"backstory\": \"...\", \"desires\": \"...\" }\n"
        "  },\n"
        "  \"style_guide\": \"Detail specific instructions: short paragraphs, fast paced dialogue, etc.\"\n"
        "}"
    )
    
    user_prompt = f"Deconstruct and generate a unique original adaptation of this input:\n\n{reference_text}"
    response_text = call_llm(system_prompt, user_prompt, json_mode=True)
    try:
        return json.loads(response_text)
    except:
        return json.loads(get_fallback_mock_response(system_prompt, user_prompt, True))

def generate_outline(title, synopsis, character_bible, target_chapters):
    """
    Stage 2: Generates a complete chapter-by-chapter outline for the target book.
    """
    system_prompt = (
        "You are an expert plot designer. Generate a structured chapter outline for a web novel. "
        "Each chapter must have a concrete structural goal and a cliffhanger hook to keep mobile readers paying for the next chapter. "
        "Return a valid JSON object containing an array of chapters. Schema exactly:\n"
        "{\n"
        "  \"outline\": [\n"
        "     { \"chapter_number\": 1, \"title\": \"...\", \"goals\": \"...\", \"cliffhanger_focus\": \"...\" }\n"
        "  ]\n"
        "}"
    )
    
    user_prompt = (
        f"Create an outline of {target_chapters} chapters for the book '{title}'.\n"
        f"Synopsis: {synopsis}\n"
        f"Character Bible: {json.dumps(character_bible)}"
    )
    
    response_text = call_llm(system_prompt, user_prompt, json_mode=True)
    try:
        return json.loads(response_text).get("outline", [])
    except:
        # Generate mock array if parsing failed
        return json.loads(get_fallback_mock_response(system_prompt, user_prompt, True)).get("outline", [])

def generate_chapter(title, style_guide, character_bible, chapter_num, chapter_title, goals, cliffhanger_focus, previous_chapter_text=""):
    """
    Stage 3: Drafts a full-length chapter based on state context and previous history.
    """
    system_prompt = (
        f"You are a bestselling web novel author. Your writing style must adhere to this guide:\n{style_guide}\n\n"
        f"Character details:\n{json.dumps(character_bible)}\n\n"
        "Write in the style of highly successful platform hits: short, dramatic paragraphs (1-3 sentences), "
        "heavy sensory descriptions, active verbs, and deep emotional stakes. "
        "Ensure the chapter concludes on a high-tension suspenseful cliffhanger."
    )
    
    user_prompt = (
        f"Write Chapter {chapter_num}: {chapter_title} for the book '{title}'.\n\n"
        f"Specific Goals to achieve in this chapter:\n{goals}\n\n"
        f"Cliffhanger to focus on:\n{cliffhanger_focus}\n\n"
    )
    
    if previous_chapter_text:
        user_prompt += f"Context from previous Chapter:\n{previous_chapter_text[-3000:]}\n\n"
        
    user_prompt += "Write the complete chapter text now. Start directly with the prose, no introduction."
    
    return call_llm(system_prompt, user_prompt, json_mode=False)

def review_and_polish_chapters(title, character_bible, style_guide, chapters_list):
    """
    Stage 4: Editor/Reviewer Agent that reviews the complete multi-chapter draft (e.g., Chapters 1-5)
    to check for plot holes, character inconsistencies, and polish prose before final submission.
    """
    system_prompt = (
        f"You are a Senior Publishing Editor specializing in high-converting web novels. "
        f"Your task is to analyze the draft of the first 5 chapters of '{title}' for structural consistency.\n\n"
        f"Character Profiles:\n{json.dumps(character_bible)}\n"
        f"Target Style Manual:\n{style_guide}\n\n"
        "Specifically, scan the text and correct:\n"
        "1. Plot inconsistencies (e.g., character actions contradict their backstory or secrets).\n"
        "2. Character detail changes (e.g., mismatched eye colors, names, or physical traits).\n"
        "3. Pacing and CLIFFHANGER optimization: Make sure each chapter ending leaves the reader highly suspenseful.\n"
        "Rewrite each chapter to be highly engaging, emotional, and consistent, while maintaining the short paragraph styling."
    )
    
    # Pack chapters text for context
    draft_data = ""
    for ch in chapters_list:
        draft_data += f"--- CHAPTER {ch['chapter_number']}: {ch['title']} ---\n{ch['content']}\n\n"

    user_prompt = (
        "Review and rewrite the following drafted chapters to ensure perfect logical consistency "
        "and elite emotional web-novel styling. Output the complete revised text, separating chapters clearly:\n\n"
        f"{draft_data}"
    )
    
    return call_llm(system_prompt, user_prompt, json_mode=False)

def get_fallback_mock_response(system_prompt, user_prompt, json_mode):
    """
    Fallback mock generator so developers can test the end-to-end local 
    dashboard even without paying for an active Azure endpoint.
    """
    if json_mode:
        if "outline" in system_prompt.lower():
            # Return dummy outline
            return json.dumps({
                "outline": [
                    {"chapter_number": i, "title": f"The Rising Dawn Part {i}", 
                     "goals": f"Setup drama, progress character arc and build tension regarding the pack secrets.", 
                     "cliffhanger_focus": "A mysterious rustle in the trees."}
                    for i in range(1, 6)
                ]
            })
        else:
            return json.dumps({
                "title": "Shadow of the Moon",
                "synopsis": "A wolf-less exile meets a rogue Alpha and discovers a secret that could break their fated bond.",
                "genre": "Werewolf Romance",
                "character_bible": {
                    "female_lead": {"name": "Lyra", "age": 22, "backstory": "Exiled wolf-less leader", "desires": "To reclaim her wolf"},
                    "male_lead": {"name": "Kaelen", "age": 24, "backstory": "Ruthless dark Alpha", "desires": "To protect Lyra"}
                },
                "style_guide": "Write with short paragraphs. End chapters with suspense."
            })
    else:
        return (
            "Lyra pulled her cloak tighter, the midnight chill slicing through her thin shirt.\n\n"
            "\"Why wouldn't he just tell me?\" she whispered. The silence of the forest offered no answer.\n\n"
            "A sudden snap of a dry branch behind her made her freeze. She spun around, but all she saw was darkness.\n\n"
            "Could it be Magnus? Or someone far worse?"
        )
