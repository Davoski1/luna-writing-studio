import os
import json
import requests

# Try to load environment variables from backend/.env manually to ensure resiliency
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

# Load environment variables (fallback to local mock values if not defined)
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "https://api.openai.com/v1/chat/completions")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")
API_MODEL = os.getenv("API_MODEL", "gpt-4o-mini")

# New explicit variables for OCR model to support dual-model pipelines
OCR_API_ENDPOINT = os.getenv("OCR_API_ENDPOINT", AZURE_OPENAI_ENDPOINT)
OCR_API_KEY = os.getenv("OCR_API_KEY", AZURE_OPENAI_KEY)
OCR_API_MODEL = os.getenv("OCR_API_MODEL", API_MODEL)

def call_llm(system_prompt, user_prompt, json_mode=False, image_base64=None, endpoint_url=None, api_key=None, model_name=None, temperature=None):
    """
    Standard request caller for Azure OpenAI / OpenAI serverless endpoints. Supports multimodal image payloads.
    Allows dynamic endpoint, key, and model overrides to support dual-model workflows.
    """
    headers = {
        "Content-Type": "application/json",
    }
    
    # Use overrides if provided, else fall back to standard settings
    endpoint_url = (endpoint_url or AZURE_OPENAI_ENDPOINT).strip()
    api_key = api_key or AZURE_OPENAI_KEY
    model_name = model_name or API_MODEL
    
    # Check if this is an Azure AI Studio serverless (MaaS) endpoint
    if "services.ai.azure.com" in endpoint_url or "inference.ai.azure.com" in endpoint_url:
        from urllib.parse import urlparse
        base_url = endpoint_url.split("?")[0]
        parsed = urlparse(base_url)
        endpoint_url = f"{parsed.scheme}://{parsed.netloc}/models/chat/completions"
        
        if "?" not in endpoint_url:
            endpoint_url += "?api-version=2024-05-01-preview"
            
        # MaaS endpoints use standard Authorization Bearer header
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        # Traditional Azure OpenAI or OpenAI keys
        if endpoint_url and not endpoint_url.endswith("/chat/completions") and not endpoint_url.endswith("/completions"):
            endpoint_url = endpoint_url.rstrip("/") + "/chat/completions"
            
        if "openai.azure.com" in endpoint_url or "azure" in endpoint_url.lower():
            headers["api-key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"

    # Prepare message payload
    user_content = user_prompt
    if image_base64:
        user_content = [
            {"type": "text", "text": user_prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_base64}"
                }
            }
        ]

    # Force temperature=0.0 for OCR to ensure high-fidelity literal translation, else use 0.7 for creative writing
    actual_temp = temperature if temperature is not None else (0.0 if image_base64 else 0.7)

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": actual_temp,
        "max_tokens": 4000
    }
    
    # Inject model name if provided or required
    if model_name:
        payload["model"] = model_name
    elif "api.openai.com" in endpoint_url or "services.ai.azure.com" in endpoint_url or "inference.ai.azure.com" in endpoint_url:
        payload["model"] = "gpt-4o-mini"
        
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

def extract_text_from_image(image_base64):
    """
    Stage 0 - Screenshot OCR Extraction: Ingests a base64 encoded screenshot image of a book chapter,
    invokes the OCR-specific vision capabilities (e.g. Mistral Document AI), and extracts only the pristine narrative prose.
    It removes mobile headers, statuses, battery icons, ads, comments, navigation bars, and watermarks.
    """
    system_prompt = (
        "You are an expert high-fidelity document OCR transcription editor. "
        "Your task is to analyze the provided screenshot of a web novel chapter and extract "
        "the raw story content text exactly as it appears. "
        "Follow these strict formatting and extraction guidelines:\n"
        "1. Extract ONLY the clean narrative prose. Do NOT include page headers, browser address bars, "
        "mobile status indicators (battery, wifi, time), advertisement banners, user comment sections, "
        "navigation links, or platform UI buttons.\n"
        "2. Keep the paragraph breaks exactly as written. Output clean paragraphs separated by double newlines.\n"
        "3. Do NOT add any conversational introduction, notes, or wrapper text. Start directly with the prose."
    )
    user_prompt = "Transcribe and extract the narrative text from this screenshot image."
    
    return call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_mode=False,
        image_base64=image_base64,
        endpoint_url=OCR_API_ENDPOINT,
        api_key=OCR_API_KEY,
        model_name=OCR_API_MODEL,
        temperature=0.0
    )

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

def generate_comprehensive_plot_bible(title, character_bible, style_guide, chapters_list):
    """
    Takes the drafted chapters list and generates a massive, 2,000-word comprehensive
    novel blueprint, deep-dive plot synopsis, lore book, and future trajectory bible.
    """
    system_prompt = (
        "You are an Elite Senior Publishing Director specializing in commercial web novel serialization. "
        "Your task is to compile a massive, deeply detailed, 2000-word Plot Bible and Comprehensive Story Narrative "
        "based on the first 5 chapters provided. Your response must be extremely thorough, formatted in beautiful "
        "Markdown, and divided into the following clear sections:\n\n"
        "1. EXECUTIVE STORY OVERVIEW & METRICS\n"
        "2. CHAPTER-BY-CHAPTER DEEP DIVE SYNOPIS (Chapters 1-5 detailed breakdowns)\n"
        "3. THE NOVEL CORE LORE BIBLE (The Obsidian Amulet, The Alpha's Shadow sigil, Prophecy mechanics, Ghost Wolves ancestry)\n"
        "4. CHARACTER RELATIONSHIP MATRIX (Maya & Kael's fated chemistry evolution, Joren's path to betrayal, Selene's motives)\n"
        "5. SEASON 2 & FUTURE ARC ROADMAP (A structured projection of Chapters 6-20, main conflicts, and the looming Obsidian Crown climax)\n\n"
        "Write with highly professional literary authority, leaving no stone unturned. Make sure the output is extensive, reaching a high word count of approximately 2000 words, detailed, and completely immersive."
    )
    
    draft_data = ""
    for ch in chapters_list:
        draft_data += f"--- CHAPTER {ch['chapter_number']}: {ch['title']} ---\n{ch['content']}\n\n"

    user_prompt = (
        f"Generate a comprehensive, 2000-word master Plot Bible based on the book '{title}' and its first 5 drafted chapters:\n\n"
        f"{draft_data}"
    )
    
    return call_llm(system_prompt, user_prompt, json_mode=False)
