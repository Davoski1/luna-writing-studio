import re
import urllib.parse
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

def clean_html(html_content, url=None):
    """
    Strips scripts, styles, forms, and returns clean readable paragraph blocks.
    Tailored extraction for AO3, Royal Road, Scribble Hub, and static paid novel mirrors.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Target-specific pristine content container selectors
    target_container = None
    
    if url:
        parsed_url = urllib.parse.urlparse(url).netloc.lower()
        if "archiveofourown.org" in parsed_url:
            # AO3 work/chapter container
            target_container = soup.find(class_="userstuff") or soup.find(role="article")
        elif "royalroad.com" in parsed_url:
            # Royal Road chapter container
            target_container = soup.find(class_="chapter-content") or soup.find(class_="chapter-inner")
        elif "scribblehub.com" in parsed_url:
            # Scribble Hub narrative block
            target_container = soup.find(id="chp_raw") or soup.find(class_="chp_raw")
        elif any(domain in parsed_url for domain in ["boxnovel.com", "novelbin", "boxnovel", "readnovelfull"]):
            # Popular mirror site containers
            target_container = (
                soup.find(class_="chr-c") or 
                soup.find(class_="chr-content") or 
                soup.find(id="chr-content") or
                soup.find(class_="chapter-c")
            )

    # Use target container if found, otherwise search entire soup
    root = target_container if target_container else soup

    # Remove clutter
    for element in root(["script", "style", "nav", "header", "footer", "form", "iframe", "noscript", "div.author-note", "div.comment"]):
        try:
            element.decompose()
        except Exception:
            pass
        
    paragraphs = []
    # Gather all paragraph texts from the cleaned root
    for p in root.find_all("p"):
        text = p.get_text().strip()
        # Avoid short noise, copyrights, and terms
        if len(text) > 20 and not text.startswith("©") and not any(term in text.lower() for term in ["terms of service", "privacy policy", "all rights reserved"]):
            paragraphs.append(text)
            
    # Fallback if no paragraphs are found inside targeted container
    if not paragraphs:
        for p in soup.find_all("p"):
            text = p.get_text().strip()
            if len(text) > 20 and not text.startswith("©") and "terms of service" not in text.lower():
                paragraphs.append(text)

    return "\n\n".join(paragraphs)

def scrape_web_novel_chapters(url):
    """
    Scrapes a web novel page. 
    Attempts to discover individual chapter links if it's an overview page,
    otherwise scrapes the text of the given page directly.
    """
    print(f"[Scraper] Scraping URL: {url}")
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"[Scraper Error] Failed to fetch URL {url}: {e}")
        return f"Error: Failed to fetch source URL: {e}"
        
    soup = BeautifulSoup(response.text, "html.parser")
    
    # Let's inspect the page. Does it look like a Table of Contents with multiple links?
    # We look for links pointing to chapters.
    domain = urllib.parse.urlparse(url).netloc
    base_url = f"{urllib.parse.urlparse(url).scheme}://{domain}"
    
    chapter_urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text().lower()
        # Look for chapter-like links: e.g. contains '/chapter', 'part', 'story/' or 'read/'
        # Or link text contains "chapter" or "part"
        is_chapter_link = False
        if any(keyword in href.lower() for keyword in ["/chapter", "-chapter", "/read/", "/story/"]):
            is_chapter_link = True
        elif any(keyword in text for keyword in ["chapter ", "part ", "prologue"]):
            is_chapter_link = True
            
        if is_chapter_link:
            full_href = urllib.parse.urljoin(url, href)
            # Avoid duplicating
            if full_href not in chapter_urls and "#" not in full_href:
                chapter_urls.append(full_href)
                
    # If we found chapter links (e.g. Table of Contents page), let's scrape the first 5 links!
    if len(chapter_urls) > 1:
        print(f"[Scraper] Found {len(chapter_urls)} potential chapter links. Scraping first 5...")
        compiled_text = []
        for index, chap_url in enumerate(chapter_urls[:5]):
            print(f"[Scraper] Scraping chapter {index + 1}: {chap_url}")
            try:
                chap_res = requests.get(chap_url, headers=HEADERS, timeout=10)
                chap_res.raise_for_status()
                chap_text = clean_html(chap_res.text, chap_url)
                if len(chap_text) > 100:
                    compiled_text.append(f"--- CHAPTER {index + 1} ({chap_url}) ---\n\n{chap_text}")
            except Exception as ex:
                print(f"[Scraper Warning] Failed to scrape chapter {chap_url}: {ex}")
                
        if compiled_text:
            return "\n\n".join(compiled_text)
            
    # Fallback: Scrape the main page directly
    print("[Scraper] No multiple chapter links found. Parsing direct page content...")
    page_text = clean_html(response.text, url)
    
    # If the text is very short, try getting all text from main container
    if len(page_text) < 500:
        # Just grab the entire text of the body, stripped
        body = soup.find("body")
        if body:
            for element in body(["script", "style", "nav", "header", "footer"]):
                try:
                    element.decompose()
                except Exception:
                    pass
            page_text = body.get_text(separator="\n\n").strip()
            # Clean up excessive spacing
            page_text = re.sub(r'\n\s*\n+', '\n\n', page_text)
            
    return page_text[:80000] # Safe limit ~15,000 words
