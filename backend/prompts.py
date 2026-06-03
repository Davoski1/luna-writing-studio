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
    Supports either a base64 encoded string or a direct public http/https image URL.
    Implements a resilient multi-model routing & fallback waterfall prioritizing OpenRouter elite models
    (Grok 4.3, DeepSeek-R1, Gemini 2.5 Flash) and automatically falling back to Azure OpenAI systems.
    """
    import time
    
    # 1. Build the waterfall sequence of endpoints to try in order: (url, key, model, source_type)
    waterfall = []
    
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    
    # If the user explicitly provided overrides via function arguments, respect them as first priority
    if endpoint_url or api_key or model_name:
        resolved_endpoint = (endpoint_url or AZURE_OPENAI_ENDPOINT).strip()
        resolved_key = api_key or AZURE_OPENAI_KEY
        resolved_model = model_name or API_MODEL
        waterfall.append((resolved_endpoint, resolved_key, resolved_model, "standard"))
    
    # If OpenRouter is configured in env, append Tier 1 (Paid OpenRouter) and Tier 2 (Free OpenRouter)
    if openrouter_key:
        or_endpoint = "https://openrouter.ai/api/v1/chat/completions"
        if image_base64 or model_name in ["Phi-4-Vision", "x-ai/grok-4.3", "x-ai/grok-4.20", "x-ai/grok-2-vision-1212", OCR_API_MODEL]:
            # Vision / OCR Tasks:
            # Tier 1: Paid Grok 4.3 / 4.20 & Paid Gemini 2.5 Flash
            waterfall.append((or_endpoint, openrouter_key, "x-ai/grok-4.3", "openrouter"))
            waterfall.append((or_endpoint, openrouter_key, "x-ai/grok-4.20", "openrouter"))
            waterfall.append((or_endpoint, openrouter_key, "google/gemini-2.5-flash", "openrouter"))
            # Tier 2: Free / Low-cost fallback models
            waterfall.append((or_endpoint, openrouter_key, "google/gemini-2.5-flash-lite", "openrouter"))
            waterfall.append((or_endpoint, openrouter_key, "nvidia/nemotron-nano-12b-v2-vl:free", "openrouter"))
        elif json_mode:
            # Logic & Planning Tasks:
            # Tier 1: Paid DeepSeek R1 & Grok 4.3
            waterfall.append((or_endpoint, openrouter_key, "deepseek/deepseek-r1", "openrouter"))
            waterfall.append((or_endpoint, openrouter_key, "x-ai/grok-4.3", "openrouter"))
            # Tier 2: Free Llama 3.3
            waterfall.append((or_endpoint, openrouter_key, "meta-llama/llama-3.3-70b-instruct:free", "openrouter"))
        else:
            # Narrative & Prose Tasks:
            # Tier 1: Paid Grok 4.3 & Paid Gemini 2.5 Flash
            waterfall.append((or_endpoint, openrouter_key, "x-ai/grok-4.3", "openrouter"))
            waterfall.append((or_endpoint, openrouter_key, "google/gemini-2.5-flash", "openrouter"))
            # Tier 2: Free Llama 3.3 & Low-cost Gemini 2.5 Flash Lite
            waterfall.append((or_endpoint, openrouter_key, "meta-llama/llama-3.3-70b-instruct:free", "openrouter"))
            waterfall.append((or_endpoint, openrouter_key, "google/gemini-2.5-flash-lite", "openrouter"))
            
    # Always ensure the original Azure system models are appended as Tier 3 (Final Fallback)
    azure_endpoint = AZURE_OPENAI_ENDPOINT.strip() if AZURE_OPENAI_ENDPOINT else ""
    azure_key = AZURE_OPENAI_KEY
    azure_model = API_MODEL
 
    # If the user has configured direct xAI API credentials to use their free console credits,
    # and this is a creative prose/drafting task (not planning or vision), prioritize direct xAI Grok at the absolute top!
    is_xai_configured = "api.x.ai" in azure_endpoint.lower()
    if is_xai_configured and not json_mode and not image_base64 and not (endpoint_url or api_key or model_name):
        xai_model = azure_model if azure_model != "gpt-oss-120b" else "grok-2"
        waterfall.insert(0, (azure_endpoint, azure_key, xai_model, "standard"))
    
    # Vision tasks have their own dedicated Azure OCR fallback variables
    if image_base64 or model_name in ["Phi-4-Vision", "x-ai/grok-4.3", "x-ai/grok-4.20", "x-ai/grok-2-vision-1212", OCR_API_MODEL]:
        azure_endpoint = OCR_API_ENDPOINT.strip() if OCR_API_ENDPOINT else ""
        azure_key = OCR_API_KEY
        azure_model = OCR_API_MODEL
        
    # Avoid duplicate identical configurations
    if not (endpoint_url or api_key or model_name):
        waterfall.append((azure_endpoint, azure_key, azure_model, "standard"))
        
    # 1.5 Always append the Azure Phi-4-Vision model as the final fallback for vision tasks
    if image_base64 or (model_name and ("vision" in model_name.lower() or "grok" in model_name.lower() or model_name == "Phi-4-Vision")):
        phi_endpoint = AZURE_OPENAI_ENDPOINT.strip() if AZURE_OPENAI_ENDPOINT else ""
        phi_key = AZURE_OPENAI_KEY
        phi_model = "Phi-4-Vision"
        if phi_endpoint and not any(w[0] == phi_endpoint and w[2] == phi_model for w in waterfall):
            waterfall.append((phi_endpoint, phi_key, phi_model, "standard"))
            
    last_exception = None
    
    # 2. Iterate through the waterfall to execute the request successfully
    for target_endpoint, target_key, target_model, source_type in waterfall:
        print(f"[LLM Router] Attempting call to model: {target_model} via {source_type}...")
        
        headers = {
            "Content-Type": "application/json",
        }
        
        # Configure endpoint url for API format
        current_endpoint = target_endpoint
        if source_type == "openrouter":
            headers["Authorization"] = f"Bearer {target_key}"
            headers["HTTP-Referer"] = "https://luna-writing-api-69542.azurewebsites.net"
            headers["X-Title"] = "Luna Writing Studio"
        else:
            # Check if this is an Azure AI Studio serverless (MaaS) endpoint
            if "services.ai.azure.com" in current_endpoint or "inference.ai.azure.com" in current_endpoint:
                from urllib.parse import urlparse
                base_url = current_endpoint.split("?")[0]
                parsed = urlparse(base_url)
                current_endpoint = f"{parsed.scheme}://{parsed.netloc}/models/chat/completions"
                if "?" not in current_endpoint:
                    current_endpoint += "?api-version=2024-05-01-preview"
                headers["Authorization"] = f"Bearer {target_key}"
            else:
                # Traditional Azure OpenAI or OpenAI keys
                if current_endpoint and not current_endpoint.endswith("/chat/completions") and not current_endpoint.endswith("/completions"):
                    current_endpoint = current_endpoint.rstrip("/") + "/chat/completions"
                if "openai.azure.com" in current_endpoint or "azure" in current_endpoint.lower():
                    headers["api-key"] = target_key
                else:
                    headers["Authorization"] = f"Bearer {target_key}"

        # Prepare message payload
        user_content = user_prompt
        if image_base64:
            # Support either direct image URL (e.g. public http/https link) or raw base64 data URI
            if image_base64.startswith("http://") or image_base64.startswith("https://"):
                image_url = image_base64
            else:
                image_url = f"data:image/jpeg;base64,{image_base64}"
                
            user_content = [
                {"type": "text", "text": user_prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image_url
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
        
        # Inject model name
        payload["model"] = target_model
        
        # B1s / Azure Serverless endpoints, custom gpt-oss-120b, and reasoning models like DeepSeek-R1 do not support json_object mode.
        if json_mode and target_model != "gpt-oss-120b" and "deepseek-r1" not in target_model.lower() and "cognitiveservices.azure.com" not in current_endpoint:
            payload["response_format"] = {"type": "json_object"}

        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                response = requests.post(current_endpoint, headers=headers, json=payload, timeout=120)
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait_sec = float(retry_after) if (retry_after and retry_after.replace('.', '', 1).isdigit()) else retry_delay
                    print(f"[LLM 429] Rate limited on {target_model}. Retrying attempt {attempt+1}/{max_retries} after {wait_sec}s...")
                    time.sleep(wait_sec)
                    retry_delay *= 2
                    continue
                
                response.raise_for_status()
                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    first_choice = result["choices"][0]
                    message = first_choice.get("message", {})
                    
                    # Gracefully handle Content Safety filters
                    if first_choice.get("finish_reason") == "content_filter":
                        raise ValueError("The narrative text or screenshot was blocked by Content Safety filters. Please try another segment.")
                    
                    # Check for direct model refusal
                    if "refusal" in message and message["refusal"]:
                        raise ValueError(f"Model refused request: {message['refusal']}")
                        
                    if "content" in message:
                        return message["content"]
                    
                raise ValueError("LLM responded with an empty or unexpected completion format.")
            except Exception as e:
                is_429 = False
                if hasattr(e, "response") and e.response is not None:
                    if e.response.status_code == 429:
                        is_429 = True
                
                if is_429:
                    wait_sec = retry_delay
                    print(f"[LLM 429] Rate limited (exception) on {target_model}. Retrying after {wait_sec}s...")
                    time.sleep(wait_sec)
                    retry_delay *= 2
                    continue
                    
                if attempt == max_retries - 1:
                    print(f"[LLM Router Error] Attempt {attempt+1} failed on {target_model}: {e}")
                    last_exception = e
                else:
                    print(f"API Call failed on {target_model} (attempt {attempt+1}): {e}. Retrying after {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
        
        print(f"[LLM Router Fallback] {target_model} failed. Cascade triggering next fallback model...")
        
    # If all models in the waterfall fail, raise the last encountered exception
    if last_exception:
        raise last_exception
    raise ValueError("All models in the LLM router routing waterfall failed to return a response.")
 
def extract_text_from_image(image_base64):
    """
    Stage 0 - Screenshot OCR Extraction: Ingests a base64 encoded screenshot image or a direct image URL of a book chapter,
    invokes the OCR-specific vision capabilities, and extracts only the pristine narrative prose.
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

def _clean_json_text(text):
    if not text:
        return ""
    text = text.strip()
    # Strip markdown block wrappers if present
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

def deconstruct_and_adapt(reference_text):
    """
    Stage 1: Analyzes the reference text to pull out structural DNA and 
    create a new, entirely unique concept and character bible.
    """
    system_prompt = (
        "You are an expert web novel publishing editor. Your task is to analyze the "
        "provided story concept and deconstruct its core elements (tropes, pacing, conflicts). "
        "Then, generate a completely original, non-plagiarized book proposal based on those tropes. "
        "Change all names, pack names, settings, and backstory events to ensure 100% original IP.\n\n"
        "STRICT STYLE, TONE, & COMPREHENSION CONSTRAINT:\n"
        "Your proposal, character descriptions, and the generated structural outline must be written at a 4th-to-5th grade reading level (around a 10-year-old's level). "
        "Use simple, direct words, short sentences, and a very clear casual voice so a child can understand the entire plot at one glance. "
        "Avoid complex vocabulary, academic jargon, and melodramatic/flowery words. "
        "Explain things using basic actions and clear feelings (e.g., 'He is sad and scared' instead of 'He is experiencing deep emotional distress'). "
        "However, do not lose the richness, drama, or exciting stakes of the story—keep it extremely engaging, emotional, and fun to read.\n\n"
        "STRICT EDITORIAL RULES FOR THE MASTER STRUCTURAL OUTLINE:\n"
        "Your generated structural outline must strictly follow these contract-winning standards:\n"
        "1. DECLARATIVE NARRATIVE ONLY (NO QUESTIONS): Never ask questions to create suspense (e.g., do NOT write 'Will Catherine survive Jackson\\'s abuse?' or 'Can he save her?'). Describe exactly what happens, how the conflicts start, how they develop, and how they end.\n"
        "2. NO SCENE-BY-SCENE ACTION OR DIALOG: Do not describe specific, low-level physical actions, scene staging, or minor step-by-step movement (e.g., 'she vomited from the taste of copper', 'cuffed to the bed', 'Eden knees him', 'pulls a gun in the boardroom', or 'stabs Damon's hand with a letter opener'). The outline must analyze and summarize major narrative events, relationship shifts, lore discoveries, and core plot turns at a macro level, not minor step-by-step scene actions. Do not write dialogue lines. Keep the outline focused on the structural framework of the narrative, reserving low-level staging and choreographies for chapter drafting.\n"
        "3. WEAK-TO-STRONG FEMALE LEAD (FL) ARC: The story must be centered around the FL. Introduce her in a weak, pitiful, or constrained position in the beginning (e.g., suffering due to bankrupt family debt, a forced abusive contract marriage, or public rejection/exile) to build deep reader empathy. Trace her gradual transformation into a strong, independent figure who gains options or power to bring the ML or villain down by the climax/denouement.\n"
        "4. CONCRETE VILLAIN MECHANICS: Clearly identify the villain (e.g., the ML, the FL's best friend, her sister, her ex, etc.). Detail the specific, active harm they commit and how it affects the FL/ML. Do not use vague statements like 'she suffered'; describe exactly what they did (e.g., 'he abused her at every chance' or 'her best friend collaborated with the second chance mate to kidnap her triplets').\n"
        "5. UNEXPECTED PLOT TWISTS & RED HERRINGS: Weave unexpected plot twists beginning at the Inciting Incident or Climax. Lead the editor/reader to suspect one character (a red herring, e.g. pointing fingers at the ex-boyfriend) before revealing the true villain or secret alliance (e.g. the billionaire husband plotting with the best friend).\n"
        "6. USE CHARACTER NAMES: Always use the actual character names generated in your character bible throughout the outline plot points. Do not use generic placeholders like FL or ML.\n"
        "7. CHARACTER CONSISTENCY: Dominant personality traits, goals, and flaws defined in the Characterization section must dictate character actions throughout the Plot. If the ML is obsessive and possessive, his decisions must create tension and lead to conflicts. If the FL is determined, she must challenge obstacles and actively drive the plot forward.\n"
        "8. CHARACTER BALANCE & CONTRAST (SUPPORTING CHARACTERS): Never write a story without supporting characters. They must have clear utility in relation to the main leads: use contrast to highlight the leads' traits (e.g., balance a brave FL with a cautious, logical best friend; highlight a possessive ML with a challenging rival). They must add depth, drive the plot by creating conflicts/resolving problems, and have their own distinct personalities/lives.\n"
        "9. HIGH NARRATIVE RICHNESS & DYNAMISM (AVOID FLAT PLOTS): A flat plot (e.g., simply entering a contract marriage, falling in love, and marrying for real without high stakes, secrets, or twists) is unacceptable. You must inject high-impact dynamism into every story, ensuring:\n"
        "   - High Emotional Stakes & Pacing: Every conflict must carry deep personal, emotional, or life-and-death consequences, making every scene feel urgent. Even in contemporary genres, stakes must extend beyond simple money or reputation to involve freedom, safety, or core trauma.\n"
        "   - Earning the Romance Payoff: The leads' relationship must progress through shared struggle, vulnerability, and mutual protection. The resolution must feature a satisfying, powerful emotional union (not just a cold business agreement or separate lives).\n"
        "   - Complex Antagonists: Antagonists must not be flat. They should have a close personal or emotional connection to the leads (e.g. former guardian, family, or a grey moral stance).\n"
        "   - Troper Subversion & Originality: The setting, lore, and conflicts must subvert clichés and add unique, fresh layers (like hidden codes, alchemical drugs, or unique family secrets) to make the book feel like a premium, original IP.\n"
        "10. FIRST 5,000 WORDS PACING & HOOKS (IMMEDIATE IMPACT): The first 5,000 words (the first 2-3 chapters) must be extremely fast-paced, carrying up to 50% of the plot's initial hook events. The Female Lead (FL) and Male Lead (ML) MUST meet within these first 5,000 words, allowing the reader to feel the intense chemistry and tension from the beginning. Bring the main action of the story directly into these opening chapters to capture the reader's interest immediately.\n"
        "11. CLIFFHANGERS & UNFINISHED SCENES: Every chapter/milestone must conclude on a high-tension suspenseful cliffhanger. This can be in the form of an unresolved question or an unfinished, cut-off dramatic scene (e.g., a door suddenly being pushed open during a secret kiss, or a mysterious car pulling up to rescue/kidnap a character, leaving the reader desperate to know what happens next).\n"
        "12. REALISTIC TIMELINE (NO TIME SKIPS IN THE BEGINNING): In the first 5,000 words (the first 2-3 chapters), avoid any time-skipping or fast-forwarding phrases (e.g. 'days went by', 'days after', or 'weeks after'). The sequence of events must flow realistically, step-by-step and hour-by-hour, showing exactly how everything unfolded. Fast-forwarding is only allowed later in the book.\n"
        "13. STRICT PARAGRAPH SPACING & LAYOUT: All prose paragraphs must be properly spaced and structured. Never have more than 5 sentences in a single paragraph (ideally 1-3 sentences max) to ensure a clean, breathable presentation for mobile readers.\n"
        "14. SHOW, DON'T TELL (VIVID SENSORY ACTION): You must show characters' feelings, actions, and reactions rather than telling or summarizing. Specifically apply these five showing techniques:\n"
        "   - Use Descriptive Language (Engage Senses): Describe what characters see, hear, smell, taste, and touch to bring scenes to life (e.g., describe 'scorching sun beating down, shimmering waves of heat rising' instead of 'it was hot').\n"
        "   - Show Character Actions & Gestures (Reveal Body Language): Use facial expressions, body movements, and gestures to convey emotions without explicitly stating them (e.g., describe 'her fists clenching, face turning red, throwing a book' instead of 'she was angry').\n"
        "   - Incorporate Dialogue: Use quick-paced banter, dialogue, and verbal arguments to show tension, relationships, and conflict in real-time.\n"
        "   - Show Through Character Thoughts (Internal Monologue): Provide direct access to the character's immediate internal thoughts and worries (e.g., describe 'His heart raced as he stared at the paper. How did I not study enough? What if I fail?' instead of 'He was worried about the test').\n"
        "   - Create Real-Time Scenes & Set the Stage: Develop scenes where actions unfold in real-time. Show the step-by-step interactions, surroundings, and immediate reactions instead of summarizing events or skipping over key emotional moments.\n"
        "15. CLOSE INTIMATE POV (FIRST OR THIRD LIMITED): Write strictly from a close, intimate perspective (either First Person 'I' or Third Person Limited 'she'/'he'). Never use Third Person Omniscient; do not explain thoughts or feelings of characters that the viewpoint character cannot witness. Focus deeply on the viewpoint character's immediate internal thoughts, raw emotions, and sensory experiences to create maximum empathy and connection.\n\n"
        "STRICT FEMALE LEAD (FL) DESIGN RULES:\n"
        "The Female Lead (FL) is the heart of the story and must be defined according to these 8 characterization parameters derived from the 17 course rules:\n"
        "1. Authenticity & Emotional Depth: Showcase a realistic range of authentic emotions (joy, fear, anger, sorrow, hope) instead of hiding behind a mask of perfection.\n"
        "2. Strength Beyond Physical: Highlight emotional resilience, intelligence, determination, and empathy.\n"
        "3. Flaws, Vulnerabilities & Realistic Struggles: Balance her strengths (intelligence, charm) with clear flaws, insecurities, and authentic struggles to make her human and relatable.\n"
        "4. Clear Goals & Purpose: Give her active desires, goals, and a sense of purpose (e.g. saving a loved one, fighting for justice) that drive her forward, rather than just reacting to others. Her choices must shape the story.\n"
        "5. Growth & Earned Transformation: Ensure she learns from mistakes, faces the consequences (both good and bad) of her choices, and undergoes an earned transition from weak to strong.\n"
        "6. Multifaceted & Unpredictable: Avoid clichés. Give her a multifaceted personality (e.g., brave yet afraid, kind yet assertive, confident yet doubtful). Keep her choices unpredictable to keep the reader guessing.\n"
        "7. Unique Backstory & Mystery: Establish a backstory that explains her fears and strengths, keeping a part of her past or hidden motives mysterious to create intrigue.\n"
        "8. Meaningful Relationships & Adaptability: Give her dynamic, active relationships with family, friends, and rivals. Show her adapting resourcefully to challenges and keeping up the fight even when she is not invincible.\n\n"
        "STRICT MALE LEAD (ML) DESIGN RULES:\n"
        "The Male Lead (ML) must be defined according to these 8 core parameters derived from the course rules:\n"
        "1. Possessive & Protective: He must care deeply about the FL and seek to keep her safe, even if it makes him overbearing or jealous of rivals due to a fear of losing her. This protective behavior must showcase his ultimate loyalty and love.\n"
        "2. Charming & Witty: He must have a quick, sharp wit. He should tease the FL playfully, using clever banter to show his affection and add lightness/humor to contrast the high tension.\n"
        "3. Flawed or Tortured: He must carry deep emotional pain, trust issues, or emotional scars from a difficult past, ensuring his growth and gradual opening-up feel meaningful and relatable.\n"
        "4. Powerful & Rich: He must hold significant status, wealth, or power (e.g. billionaire tycoon, Mafia leader, or Lycan Alpha), making him confident and capable of taking charge. His power must not just be a tool, but a source of narrative conflict (e.g., creating a wall between him and others).\n"
        "5. Being in Control (Shaken by Love): He is always in control of his emotions, environment, and decisions to handle crises and protect others. However, the FL must be the one sole vulnerability who can completely shake his control, forcing him to realize he cannot control love.\n"
        "6. Strong & Competent: He is physically strong and highly skilled in his field or profession, making him a highly capable character.\n"
        "7. Key Competence: He must excel in a specific skill or area of intelligence that makes him stand out as highly competent and remarkable.\n"
        "8. Emotional Vulnerability: Show clear moments where his walls come down and he shows vulnerability (e.g. heartbreak, fear, or struggling to trust), making him deeply human and relatable.\n\n"
        "Your response must be a valid JSON object matching this schema exactly:\n"
        "{\n"
        "  \"title\": \"Catchy, high-appeal web novel title generated from the core story idea or blurb\",\n"
        "  \"synopsis\": \"A short, catchy, and intriguing description or blurb of the story designed to lure readers in and spark curiosity. This is the only place in the proposal where you should ask a suspenseful hook question (e.g., 'But when fate offers Catherine a second chance at love, will she embrace the opportunity to rewrite her destiny?').\",\n"
        "  \"genre\": \"e.g., Werewolf Romance, Dark Fantasy\",\n"
        "  \"character_bible\": {\n"
        "     \"female_lead\": { \"name\": \"...\", \"age\": 22, \"backstory\": \"...\", \"desires\": \"...\" },\n"
        "     \"male_lead\": { \"name\": \"...\", \"age\": 24, \"backstory\": \"...\", \"desires\": \"...\" }\n"
        "  },\n"
        "  \"style_guide\": \"Detail specific instructions: short paragraphs, fast paced dialogue, etc.\",\n"
        "  \"structural_outline\": \"The Markdown outline formatted exactly as requested\"\n"
        "}\n\n"
        "The `structural_outline` field MUST contain a Markdown-formatted outline structured exactly like this:\n"
        "# [Title]\n"
        "**Genre**: [Genre]\n"
        "**Trope**: [Trope]\n"
        "**Theme**: [Theme]\n"
        "**Setting**: [Setting]\n\n"
        "## Character Ledger\n"
        "### Main Characters\n"
        "* **[FL Name]** ([Age]): [Deep description of goals, flaws, struggles, and growth curve]\n"
        "* **[ML Name]** ([Age]): [Description of power, strengths, flaws, and relationship role]\n\n"
        "### Supporting & Minor Characters\n"
        "* **[Character Name]** ([Age]): [Detailed role and plot utility]\n\n"
        "## Master Narrative Plot\n"
        "### Exposition\n"
        "[2-3 paragraphs of deep, high-stakes exposition setting up the world, history, rules, and starting state of the characters. Focus on macro narrative arcs, lore, and emotional/relationship trajectories. Absolutely no low-level physical scene actions, lines of dialogue, or immediate sensory reactions.]\n\n"
        "### Inciting Incident\n"
        "[2-3 paragraphs detailing the catalyst, the spark, the initial meeting, and the immediate consequences, focused entirely on the macro stakes.]\n\n"
        "### Rising Action\n"
        "[3-4 paragraphs tracing the development of trust, the obstacles, the discovery of secrets, and the escalating tension.]\n\n"
        "### Midpoint\n"
        "[2-3 paragraphs detailing the unmasking of the hidden enemy, the betrayal, and the paradigm shift.]\n\n"
        "### Climax\n"
        "[2-3 paragraphs describing the convergence of crises and the ultimate choice/confrontation.]\n\n"
        "### Resolution\n"
        "[2-3 paragraphs outlining the aftermath, the breaking of the curse/system, the new order, and future setup.]\n\n"
        "Here is the gold standard example of the tone, style, and layout for the structural outline:\n"
        "--- Gold Standard Example ---\n"
        "# The Moon's Cold Edge\n"
        "**Genre**: Werewolf Romance\n"
        "**Trope**: Rejected mate / Second chance mate / Fated mate\n"
        "**Theme**: Love / Revenge / Duty\n"
        "**Setting**: MYSTICAL WORLD, MOONSTONE\n\n"
        "## Character Ledger\n"
        "### Main Characters\n"
        "* **Hazel** (22): Silver-blooded killer, cold, logical, trained to execute the Wolf King. She starts vulnerable and hiding her identity, but seeks control over her own fate. Her blood is literal silver, toxic to werewolves.\n"
        "* **Lycan** (26): The cursed Wolf King, ruthless, quiet, bound by a prophecy of blood. He carries a curse that slowly hollows out the king from the inside, replacing their soul with a Voidwalker.\n\n"
        "### Supporting & Minor Characters\n"
        "* **Sera** (35): Hazel's former commander, manipulative. She seeks to kill Hazel to bury the Citadel's secrets and drives the main conflict.\n"
        "* **Wren** (20): Hazel's long-lost sister who acts as Hazel's vulnerability and emotional motivation.\n\n"
        "## Master Narrative Plot\n"
        "### Exposition\n"
        "The world is split into two powers that have hated each other for three hundred years. On one side is the Silver Citadel, a fortress city built by humans who learned how to breed silver-blooded warriors whose very blood is toxic to werewolves. On the other side is the Werewolf Kingdom, ruled by the Alpha bloodline, a dynasty that has held together an entire species through sheer force of will. The two sides have maintained a cold peace for decades. Beneath that peace, both sides are preparing for a war they believe is coming, unaware that the war has already been arranged.\n\n"
        "Hazel is twenty-four years old and has been a trained killer since she was twelve. Her blood is literal silver, burning werewolves on contact like acid. She has spent her whole life being told this makes her special. She does not remember her parents, having only one memory of a younger sister, Wren, taken from her when they were children. Hazel has built her entire identity on being useful, controlled, and unafraid. On the other hand, Lycan is twenty-nine years old and is running out of time. He carries a three-hundred-year-old bloodline curse that slowly hollows out every Wolf King from the inside, replacing their soul piece by piece with a Voidwalker. Lycan has made peace with it, and his execution is scheduled. What he does not know is that the cure has just entered his territory wearing a disguise and carrying a blade meant for his heart.\n\n"
        "### Inciting Incident\n"
        "Hazel enters Lycan's territory disguised as a foreign trade envoy, using an alchemical dampener to suppress her silver blood. She plays her role well, professional and focused, but is deeply unsettled by what she sees. It is a kingdom in mourning: exhausted soldiers, and a king who walks alone at night, pressing his hand to the frozen ground as if listening to something dying. On the third night, the Citadel-manufactured dampener fails early. Her silver blood begins seeping light from her skin, and she glows. As she tries to run, Lycan is already there, and the mate bond snaps between them.\n\n"
        "The mate bond is violent and disorienting. Hazel grabs her blade on instinct, and Lycan grabs her wrist, burning immediately as her glowing skin touches his. The mate bond physically prevents them from killing each other. Lycan takes her inside and demands answers. She tells him she is silver-blooded, sent by the Citadel to kill him. Unknowingly, the mate bond accelerates Lycan's curse. Recognizing its mate, his body fights harder, cutting his remaining time in half to six weeks. He notices this but hides it from her.\n\n"
        "### Rising Action\n"
        "Lycan does not execute or imprison Hazel, keeping her close because the mate bond makes distance uncomfortable and he needs answers. They make a deal: she will tell him about the Citadel's plans, and he will explain why the reports of a werewolf attack were false. Over the next few days, they discover a prophecy carved into the throne room wall that becomes readable only in Hazel's presence. It describes a silver-blooded Moonwright who can break the curse, but only if the key consents to break itself open.\n\n"
        "Hazel investigates the Citadel's records and discovers she is a descendant of the Moonwrights, ancient alchemists who helped design the curse three centuries ago and bound their children into living keys to undo it. She realizes the alchemical dampeners she has taken her entire life were a slow poison designed by the Citadel to suppress her Moonwright power. If she stops taking them, she has six weeks before her silver blood becomes uncontrollable; if she continues, she has four months to live. Meanwhile, she and Lycan begin to trust each other, learning one another in the language of almost-touches to avoid burning him.\n\n"
        "### Midpoint\n"
        "The hidden enemy is unmasked: Commander Sera, Hazel's guardian who raised her, has been running a secret operation for decades. Sera has been cultivating a rogue werewolf faction called the Ashwalkers, feeding both sides misinformation to engineer a catastrophic war. Her goal is to trigger a secondary prophecy requiring both a Moonwright and a Voidwalker to die simultaneously, collapsing the barrier between the human and werewolf worlds to force both species to rebuild from nothing.\n\n"
        "Hazel tracks a second silver-blood signature and finds her sister Wren, who is alive and working with Sera. Wren chose to join Sera willingly, believing the world that turned Hazel into a weapon deserves to burn. During an Ashwalker border attack, Lycan loses control, his eyes turning black. Hazel is the only one who can reach him through their bond, but they realize they only have days before his transformation completes. They must retrieve the Moonflower, a legendary plant in the dead zone of Ashwald that can neutralize her blood's toxicity, allowing them to touch and unlocking her Moonwright power.\n\n"
        "### Climax\n"
        "In the center of the Ashwald, Hazel touches the Moonflower, neutralizing her toxicity and allowing Lycan to hold her hand. However, the flower also opens her Moonwright power fully, showing her that the prophecy's sacrifice is a choice, not a mandate. Returning to the capital, three crises converge: the Ashwalker army attacks, the Citadel forces invade believing Lycan has transformed, and Lycan begins to lose himself completely.\n\n"
        "Sera activates her secondary prophecy ritual in the Ashwald, using Wren as a living anchor. Lycan, learning what breaking the curse will cost Hazel, refuses to let her sacrifice herself and tells his general to execute him. However, Wren undergoes a change of heart and disrupts Sera's ritual from the inside, burning through her own power. Free to act, Hazel channels her Moonwright power fully, channeling generations of grief and the full force of her silver blood into the corruption eating Lycan's bloodline.\n\n"
        "### Resolution\n"
        "Hazel does not die; the Moonflower changes how her power works, burning out the alchemical damage and rebuilding her as the first of something new—a bridge between species. The curse shatters, and the Voidwalker corruption drains from Lycan. The dead zone of Ashwald begins to bloom with green soil and new life, while the spirits of the previous kings are freed.\n\n"
        "Sera is captured and stripped of her status, while Wren and Hazel begin the slow process of rebuilding their sisterly bond. The Citadel's leadership fractures, the Ashwalkers disband, and Lycan's kingdom enters a state of hopeful recovery. They assemble at a council table to build a new future together.\n"
    )
    
    user_prompt = f"Deconstruct and generate a unique original adaptation of this input:\n\n{reference_text}"
    response_text = call_llm(system_prompt, user_prompt, json_mode=True)
    try:
        return json.loads(_clean_json_text(response_text))
    except Exception as e:
        print(f"Failed to parse adaptation JSON. Raw LLM response: {response_text}")
        raise ValueError(f"Adaptation JSON parsing failed: {e}. Raw response: {response_text}")

def generate_outline(title, synopsis, character_bible, target_chapters, structural_outline=""):
    """
    Stage 2: Generates a complete chapter-by-chapter outline for the target book.
    """
    system_prompt = (
        "You are an expert plot designer. Generate a structured chapter outline for a web novel. "
        "Each chapter must have a concrete structural goal and a cliffhanger hook to keep mobile readers paying for the next chapter.\n\n"
        "STRICT CHAPTER MAPPING RULE:\n"
        "You must base the chapter goals and hooks strictly on the Master Structural Outline provided.\n"
        "Map the chapters to the 6 major Narrative Plot stages from the Master Structural Outline:\n"
        "- Exposition (Focus heavily on the fated catalyst/betrayal/rejection/tragedy and meeting FL/ML)\n"
        "- Inciting incident (Focus on the turning point that binds FL and ML together)\n"
        "- Rising Action (Develop training, obstacles, or secrets)\n"
        "- Midpoint (The paradigm shift, hidden enemy reveal, or major betrayal)\n"
        "- Climax (The peak conflict, confrontation, or major reveal/ritual)\n"
        "- Resolution / Denouement (The aftermath, breaking the curse/system, happy union, or new order)\n\n"
        "STRICT COMPREHENSION RULE:\n"
        "All chapter titles, goals, and cliffhanger descriptions must be written in simple, clear language that a 10-year-old can read and understand instantly. "
        "Use short sentences and basic, easy words, while still keeping the drama, excitement, and clear goals of each chapter.\n\n"
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
        f"Character Bible: {json.dumps(character_bible)}\n"
    )
    if structural_outline:
        user_prompt += f"Master Structural Outline:\n{structural_outline}\n"
    
    response_text = call_llm(system_prompt, user_prompt, json_mode=True)
    try:
        return json.loads(_clean_json_text(response_text)).get("outline", [])
    except Exception as e:
        print(f"Failed to parse outline JSON. Raw LLM response: {response_text}")
        raise ValueError(f"Outline JSON parsing failed: {e}. Raw response: {response_text}")

def generate_chapter(title, style_guide, character_bible, chapter_num, chapter_title, goals, cliffhanger_focus, previous_chapter_text="", style_example_chapter=None, structural_outline=""):
    """
    Stage 3: Drafts a full-length chapter based on state context and previous history.
    Inserts aggressive emotional hook guidelines for Chapter 1 and the first 5 chapters.
    """
    # For Chapter 1 and the first 5 chapters, aggressively push emotional pacing and immediate fated mate hooks.
    emotional_hook_instruction = ""
    if chapter_num == 1:
        emotional_hook_instruction = (
            "\n\nSTRICT CHAPTER 1 EMOTIONAL HOOK RULE:\n"
            "This is the opening chapter of the book. You must plunge the reader directly into high-stakes, "
            "visceral emotion immediately in the opening sentences. Focus heavily on a traumatic catalyst: the fated "
            "mate rejection, a shocking pack betrayal, a brutal public exile, or a dangerous rogue meeting. "
            "Use highly active verbs and deep internal monologue to convey panic, heartbreak, pride, and sensory shock. "
            "Do NOT write slow build-up, dry exposition, or distant summaries. Start in the heat of the action. "
            "The Female Lead (FL) and Male Lead (ML) MUST meet within the first 2-3 chapters (first 5,000 words), so establish their "
            "intense chemistry and heat immediately. Conclude the chapter on an irresistible high-tension cliffhanger (an unresolved question "
            "or a cut-off, unfinished scene like a door suddenly being pushed open while kissing or a car pulling up to rescue/kidnap with 'get in quickly')."
        )
    elif chapter_num <= 5:
        emotional_hook_instruction = (
            "\n\nFAST-PACED EMOTIONAL HOOKS RULE (FIRST 5 CHAPTERS / 5,000 WORDS):\n"
            "This is one of the crucial first 5 chapters. The pace must remain extremely high (carrying up to 50% of the plot's initial hook events), "
            "building rapid momentum with active emotional stakes, physical sparks, and immediate threats. Keep paragraphs short (1-3 sentences), "
            "focus on immediate scenes rather than reflection, and ensure the FL and ML have met and are interacting with intense chemistry. "
            "Always build toward and end on an irresistible cliffhanger, such as a suspenseful question or a cut-off unfinished scene."
        )

    structural_outline_instruction = ""
    if structural_outline:
        structural_outline_instruction = f"\n\nMASTER STRUCTURAL OUTLINE:\nUse the following master plot roadmap to guide the narrative trajectory:\n{structural_outline}\n"

    system_prompt = (
        f"You are a bestselling web novel author. Your writing style must adhere to this guide:\n{style_guide}\n\n"
        f"Character details:\n{json.dumps(character_bible)}\n\n"
        f"{structural_outline_instruction}"
        "STRICT PROSE STYLE, GRAMMAR, & COMPREHENSION RULES:\n"
        "1. Write in a highly accessible, clear, and casual voice matching a 4th-to-5th grade reading level (around a 10-year-old's level) so it is instantly readable. Use simple words and natural slang. Avoid big dictionary words, complex metaphors, or fancy phrasing.\n"
        "2. Do NOT use complex, rigid, or perfect grammar. Mirror natural thought patterns: allow fragments, short sentences, conversational contractions, and a loose voice.\n"
        "3. Maintain deep emotional tension, suspense, and drama using simple, punchy, active sentences. Keep paragraphs short (1-3 sentences max). Use clear sensory details (smells, cold skin, fast heartbeat) rather than melodramatic words.\n"
        "4. Keep the drama grounded. Let the characters react with raw, quiet, realistic shock or quiet passion, rather than theatrical sighs, screaming, or grand monologues.\n"
        "5. STRICT PARAGRAPH SPACING & LAYOUT: Never have more than 5 sentences in a single paragraph (ideally 1-3 sentences max) to ensure easy readability on mobile devices.\n"
        "6. REALISTIC TIMELINE (NO TIME SKIPS IN THE BEGINNING): In the first 5,000 words (the first 2-3 chapters), avoid any time-skipping or fast-forwarding phrases (e.g. 'days went by', 'days after', or 'weeks after'). The sequence of events must flow realistically, step-by-step and hour-by-hour, showing exactly how everything unfolded. Fast-forwarding is only allowed later in the book.\n"
        "7. SHOW, DON'T TELL (VIVID SENSORY ACTION): You must show characters' feelings, actions, and reactions rather than telling or summarizing. Specifically: (a) Use Descriptive Language to engage the 5 senses, (b) Show Character Actions & Gestures like clenching fists or blushing, (c) Incorporate quick-paced Dialogue/banter to show tension, (d) Show thoughts/worries through close Internal Monologue, and (e) Create real-time scenes set in the moment instead of summarizing.\n"
        "8. CLOSE INTIMATE POV (FIRST OR THIRD LIMITED): Write strictly from a close, intimate perspective (either First Person 'I' or Third Person Limited 'she'/'he'). Never use Third Person Omniscient; do not explain thoughts or feelings of characters that the viewpoint character cannot witness.\n"
        "Ensure the chapter concludes on a high-tension suspenseful cliffhanger."
        f"{emotional_hook_instruction}"
    )
    
    user_prompt = (
        f"Write Chapter {chapter_num}: {chapter_title} for the book '{title}'.\n\n"
        f"Specific Goals to achieve in this chapter:\n{goals}\n\n"
        f"Cliffhanger to focus on:\n{cliffhanger_focus}\n\n"
    )
    
    if previous_chapter_text:
        user_prompt += f"Context from previous Chapter:\n{previous_chapter_text[-3000:]}\n\n"
        
    if style_example_chapter and len(style_example_chapter.strip()) > 0:
        user_prompt += (
            f"### GOLD-STANDARD REFERENCE CHAPTER PROSE (STYLE ONLY - DO NOT COPY CONTENT):\n"
            f"{style_example_chapter}\n\n"
            f"### STYLE DIRECTION RULES FOR CHAPTER GENERATION:\n"
            f"1. Analyze the reference chapter prose above. Mirror its paragraph layout cadence, dialogue tag variety, and sentence-level active voice formatting.\n"
            f"2. Mimic the level of dramatic tension and sensory richness shown in this reference prose.\n"
            f"3. STRICT CONSTRAINT: Do NOT copy or leak any character names, lore terms, settings, or events from the reference chapter. Apply ONLY its unique writing style and flow to draft this new chapter.\n\n"
        )

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
        "4. Tone Check: Strip away overly theatrical/flowery language or big fancy words. Ensure the dialogue is casual, the grammar is simple and conversational, and the scene retains raw poetic tension.\n"
        "Rewrite each chapter to be highly engaging, emotional, and consistent, while maintaining the short paragraph styling."
    )
    
    # Pack chapters text for context
    draft_data = ""
    for ch in chapters_list:
        draft_data += f"--- CHAPTER {ch['chapter_number']}: {ch['title']} ---\n{ch['content']}\n\n"

    user_prompt = (
        "Review and rewrite the following drafted chapters to ensure perfect logical consistency, "
        "casual modern dialogue, raw poetic tension, and elite emotional web-novel styling. Output the complete revised text, separating chapters clearly:\n\n"
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
            # Return high-hook dummy werewolf romance outline that starts with immediate rejection/exile catalyst
            return json.dumps({
                "outline": [
                    {
                        "chapter_number": 1, 
                        "title": "The Shattered Bond", 
                        "goals": "Introduce fated wolf-less leader Lyra. Dramatize her public fated mate rejection and pack betrayal by Alpha Magnus, culminating in her cold banishment.", 
                        "cliffhanger_focus": "Lyra crossing the border line into the dark, rogue-infested Obsidian Forest."
                    },
                    {
                        "chapter_number": 2, 
                        "title": "Obsidian Shadows", 
                        "goals": "Lyra running from low-level rogue beasts in the dark forest. Reconcile with dark Alpha Kaelen who rescues her and senses a secondary, forbidden fated bond.", 
                        "cliffhanger_focus": "The physical spark of Kaelen's touch revealing their fated marks."
                    },
                    {
                        "chapter_number": 3, 
                        "title": "The Alpha's Decree", 
                        "goals": "Lyra is brought to the Obsidian pack camp. Build direct conflict with Selene, who fears Lyra's arrival, and Joren, who harbors hidden greed. Kaelen declares her safety.", 
                        "cliffhanger_focus": "Selene whispering a warning to Lyra about Kaelen's dark ancestry."
                    },
                    {
                        "chapter_number": 4, 
                        "title": "Fated Whispers", 
                        "goals": "Kaelen reveals the ancient fated hybrid prophecy and pack secrets to Lyra. Progress fated chemistry between them while Joren plots in the dark.", 
                        "cliffhanger_focus": "Lyra overhearing Joren arranging a rogue border assault."
                    },
                    {
                        "chapter_number": 5, 
                        "title": "Obsidian Power Unleashed", 
                        "goals": "Joren attempts to steal the ancient Obsidian Amulet and frame Lyra. Lyra intervenes, unexpectedly triggering her own hidden hybrid moon powers to stop him.", 
                        "cliffhanger_focus": "A massive howl echoing from the borders as rogue forces launch an assault."
                    }
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

def generate_comprehensive_plot_bible(title, genre, synopsis, character_bible, structural_outline, style_guide, chapters_list, plot_summary_example=None):
    """
    Takes the drafted chapters list and generates a massive, 2,000-word comprehensive
    novel blueprint, deep-dive plot synopsis, lore book, and future trajectory bible.
    """
    system_prompt = (
        "You are an Elite Senior Publishing Director specializing in commercial web novel serialization. "
        "Your task is to compile a massive, deeply detailed, 2000-word Plot Bible and Comprehensive Story Narrative "
        "based on the provided book metadata, character bible, structural outline, and drafted chapters. "
        "Your response must be extremely thorough, formatted in beautiful Markdown, and divided into the following clear sections:\n\n"
        "1. EXECUTIVE STORY OVERVIEW & METRICS\n"
        "2. OVERALL STORY NARRATIVE SUMMARY (This section must be written as a continuous, cohesive narrative summary "
        "in a continuous essay format without nested markdown headers or subheadings. It must seamlessly map the entire story "
        "arc through 7 distinct serialized storytelling milestones:\n"
        "   - Milestone 1: Status Quo & Catalyst (Introduction, setup, and key status quo shattering event)\n"
        "   - Milestone 2: Inciting Incident (Initial major catalyst / entering new situation or danger)\n"
        "   - Milestone 3: Rising Action & Obstacles (Tension, rivals, close circle friction, secondary chemistry)\n"
        "   - Milestone 4: Midpoint/Shift (Lore revelation, power awakening, or key plot twist shift)\n"
        "   - Milestone 5: The Crisis/Betrayal (Internal betrayal, framing plot, or severe obstacle)\n"
        "   - Milestone 6: Climax/Resolution of the first major arc (High stakes conflict outbreak & key resolution)\n"
        "   - Milestone 7: The Cliffhanger Hook for future arcs (Seeding future hooks)\n"
        "Do NOT write separate chapter summaries; synthesize these milestones into one continuous, high-converting narrative essay. "
        "CRITICAL RULE: Focus strictly on the high-level narrative beats, emotional/relationship shifts, lore developments, and overarching conflicts. "
        "Do NOT write specific scene-by-scene physical actions, dialogue lines, minor step-by-step physical movement, or graphic/melodramatic violence "
        "(such as characters getting handcuffed, falling chandeliers cutting cheeks, specific dialogue arguments, vomiting, or hand-to-hand combat details). "
        "Leave all physical staging, choreography, and low-level scene actions to the detailed chapter outline and prose generation. Keep this summary macro-focused.)\n"
        "3. THE NOVEL CORE LORE BIBLE (Detail the core lore elements, magic systems, contract mechanics, family secrets, or setting rules of this specific book. Use the actual terms and concepts of this story, NOT generic placeholder terms or werewolf concepts unless the book is actually a werewolf story.)\n"
        "4. CHARACTER RELATIONSHIP MATRIX (Detail the dynamics, tension, secrets, and chemistry between the major characters, specifically using their actual names and roles defined in the character bible.)\n"
        "5. STORY PROGRESSION & PROJECTED ENDING (A heavy, detailed projection into how the story is to progress through "
        "future arcs, relationship evolutions, key plot turning points, the definitive path to resolution, and exactly "
        "how the story is projected to end in a high-tension climax.)\n\n"
        "Write with highly professional literary authority, leaving no stone unturned. Make sure the output is extensive, reaching a high word count of approximately 2000 words, detailed, and completely immersive."
    )
    
    draft_data = ""
    for ch in chapters_list:
        draft_data += f"--- CHAPTER {ch['chapter_number']}: {ch['title']} ---\n{ch['content']}\n\n"

    user_prompt = (
        f"Generate a comprehensive, 2000-word master Plot Bible based on the book details:\n"
        f"Title: {title}\n"
        f"Genre: {genre}\n"
        f"Synopsis: {synopsis}\n"
        f"Character Bible: {character_bible}\n"
        f"Structural Outline: {structural_outline}\n\n"
        f"First drafted chapters:\n\n"
        f"{draft_data}"
    )
    if plot_summary_example and len(plot_summary_example.strip()) > 0:
        user_prompt += (
            f"\n\n### PLOT BIBLE REFERENCE EXAMPLE:\n"
            f"Use the following example plot bible summary as a gold-standard guide for style, tone, and formatting in Section 2:\n"
            f"{plot_summary_example}\n"
        )
    
    return call_llm(system_prompt, user_prompt, json_mode=False)

def generate_character_bible(title, synopsis, chapters_list):
    """
    Scans the drafted chapters and synopsis to build a highly detailed, structured
    Character Bible containing all active characters in the book.
    """
    system_prompt = (
        "You are an expert character designer and story developer. Your task is to analyze the "
        "provided book title, synopsis, and drafted chapters, and build a highly detailed, structured "
        "Character Bible. You must identify the major characters (Female Lead, Male Lead, Antagonist, Supporting) "
        "and return a valid JSON object matching this schema exactly:\n\n"
        "{\n"
        "  \"female_lead\": { \"name\": \"...\", \"age\": 22, \"backstory\": \"...\", \"desires\": \"...\" },\n"
        "  \"male_lead\": { \"name\": \"...\", \"age\": 24, \"backstory\": \"...\", \"desires\": \"...\" },\n"
        "  \"rival_alpha_or_antagonist\": { \"name\": \"...\", \"age\": 26, \"backstory\": \"...\", \"desires\": \"...\" },\n"
        "  \"supporting_betrayer_or_ally\": { \"name\": \"...\", \"age\": 25, \"backstory\": \"...\", \"desires\": \"...\" }\n"
        "}"
    )
    
    draft_data = ""
    for ch in chapters_list:
        draft_data += f"--- CHAPTER {ch['chapter_number']}: {ch['title']} ---\n{ch['content']}\n\n"

    user_prompt = (
        f"Generate a detailed character bible for the novel '{title}' with synopsis:\n{synopsis}\n\n"
        f"Based on these drafted chapters:\n{draft_data}"
    )
    
    response = call_llm(system_prompt, user_prompt, json_mode=True)
    try:
        # Verify and clean it is valid JSON
        cleaned = _clean_json_text(response)
        json.loads(cleaned)
        return cleaned
    except Exception as e:
        print(f"Failed to parse character bible JSON. Raw LLM response: {response}")
        raise ValueError(f"Character Bible JSON parsing failed: {e}. Raw response: {response}")

def humanize_chapter_prose(chapter_text, style_example_chapter=None):
    """
    Polishes a chapter draft using our elite raw human storytelling guidelines.
    Forces dynamic sentence lengths, conversational rhythms, breaks grammar rules for pacing,
    bans repetitive formatting and overused em dashes, enforces active voice, and strips AI clichés.
    Supports mirroring a custom gold-standard style example chapter if provided.
    """
    system_prompt = (
        "You are my smart, highly creative co-writer and premium literary editor. "
        "We are rewriting a chapter draft so it feels 100% alive, spontaneous, and human. "
        "Talk to me and rewrite the narrative like a smart friend telling a gripping story at a coffee shop—"
        "using a warm first-person perspective (\"I\" and \"We\") in your internal workflow to collaborate with me.\n\n"
        "### DIRECTIVES FOR RAW HUMAN STORYTELLING:\n\n"
        "1. Persona & Relatable Tone\n"
        "   - Write naturally, conversational, and direct. Avoid detached, clinical, or academic prose.\n"
        "   - Ensure the language, vocabulary, and grammar match a 4th-to-5th grade reading level (around a 10-year-old's level) so it is extremely simple to read and understand at first glance, while preserving the emotional depth, action, and suspense.\n"
        "   - Ensure the internal pacing feels intimate and deeply connected, like a close friend sharing a dramatic secret.\n\n"
        "2. Sentence Rhythm & Spontaneous Cadence (Burstiness)\n"
        "   - Vary your sentence structures and lengths. Combine very brief, punchy statements with longer, flowing descriptions.\n"
        "   - Natively insert occasional sentence fragments, single-word sentences, or rhetorical questions for natural emphasis.\n"
        "   - Break the rules of perfect textbook grammar if it makes the text flow more spontaneously (e.g., start sentences with \"And\" or \"But\", or use rapid-fire clauses during action scenes).\n\n"
        "3. Active Voice & Word Choice (The Anti-Jargon List)\n"
        "   - Write strictly in the active voice. Replace weak passive constructions (e.g., \"was walking\", \"could be seen\", \"seemed to feel\") with sharp, visceral verbs.\n"
        "   - Remove all formal, academic filler phrases and AI buzzwords. Strictly ban:\n"
        "     * delve, furthermore, moreover, testament, in conclusion, whilst, intricate dance, tapestry, harbinger, shrouded\n"
        "     * beckon, resonate, dance of, shadows, echoes, realm, maze, symphony, only time would tell\n\n"
        "4. Formatting Constraints & Boundaries\n"
        "   - Keep paragraphs incredibly short (2–3 lines maximum) to improve readability and visual tension.\n"
        "   - Ban highly specific AI formatting indicators: Do NOT overuse em dashes (—) or colon-separated lists.\n"
        "   - Preserve all original plot elements, dialogue meanings, character names, and lore anchors. Elevate the voice and flow, but keep the story grounded."
    )
    
    user_prompt = f"Here is the draft I need us to humanize:\n\n{chapter_text}\n\n"
    if style_example_chapter and len(style_example_chapter.strip()) > 0:
        user_prompt += (
            f"### GOLD-STANDARD REFERENCE CHAPTER PROSE (STYLE ONLY - DO NOT COPY CONTENT):\n"
            f"{style_example_chapter}\n\n"
            f"### STYLE DIRECTION RULES FOR DRAFT HUMANIZATION:\n"
            f"1. Analyze the reference chapter prose above. Mirror its vocabulary choice, paragraph rhythm, dialogue syntax, and sentence cadence.\n"
            f"2. Mimic the level of detail, emotional internal monologue vs external action shown in this reference.\n"
            f"3. STRICT CONSTRAINT: Do NOT copy any character names, terms, settings, or events from the reference chapter. Apply ONLY its unique writing style to rewrite our draft chapter.\n\n"
        )
        
    user_prompt += "Start directly with the humanized prose, no intro or wrapper text."
    
    # We use your high-capacity creative model (gpt-oss-120b)
    return call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_mode=False,
        model_name="gpt-oss-120b"
    )

def humanize_plot_bible_content(plot_bible_text):
    """
    Polishes and humanizes the plot bible and narrative arc, elevating the storytelling tone,
    deepening the character relationship structures, and removing robotic filler.
    """
    system_prompt = (
        "You are my smart, highly creative co-writer and premium literary editor. "
        "We are rewriting a Plot Bible and Story Roadmap so it feels 100% alive, organic, and professional. "
        "Talk to me and polish the concepts like a smart friend sharing a deep, masterfully plotted saga at a coffee shop.\n\n"
        "### DIRECTIVES FOR RAW HUMAN LITERARY DEVELOPMENT:\n\n"
        "1. Persona & Tone\n"
        "   - Use conversational, immersive, and vivid language. Avoid sterile, mechanical, or textbook-like outlines.\n"
        "   - Plunge the concepts into sensory depth—explain lore, relationships, and ending trajectories in highly visceral and emotional terms.\n\n"
        "2. Spontaneous Sentence Rhythm & Flow\n"
        "   - Vary sentence lengths and structures. Combine brief, intense descriptions with flowing, complex ideas.\n"
        "   - Break rigid grammar constraints where it yields a more organic, captivating narrative voice.\n\n"
        "3. Active Voice & Banned AI Markers\n"
        "   - Maintain active constructions and high verb variety.\n"
        "   - Strictly ban repetitive AI transitional buzzwords (e.g. delve, furthermore, moreover, testament, in conclusion, tapestry, intricate dance, shrouded).\n\n"
        "4. Strict Data Preservation\n"
        "   - Do NOT omit, modify, or rewrite any core facts, names, setting elements, lore structures, or milestones. Elevate the tone, but do not change the story itself."
    )
    user_prompt = f"Here is the Plot Bible I need us to humanize:\n\n{plot_bible_text}\n\nStart directly with the humanized markdown text, preserving all headers."
    return call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_mode=False,
        model_name="gpt-oss-120b"
    )


