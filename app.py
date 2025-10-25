import streamlit as st
from playwright.sync_api import sync_playwright
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
import os, json, re, time

# ---------- SETUP ----------
load_dotenv()
DEFAULT_KEY = os.getenv("OPENAI_API_KEY")

st.set_page_config(page_title="ChatGPT Search Analyzer", layout="wide")
st.title("🧠 ChatGPT Search Behavior Analyzer (Persistent Login)")

st.write("""
Detta verktyg:
1️⃣ Tar din huvudprompt  
2️⃣ Skapar 10 variationer via GPT-4o  
3️⃣ Kör alla variationer i samma inloggade ChatGPT-session  
4️⃣ Hämtar *search_model_query* direkt från ChatGPT:s web-backend  
""")

# ---------- SIDOPANEL ----------
st.sidebar.header("API-nyckel")
use_default_api = st.sidebar.checkbox("Använd OpenAI-nyckel från .env", value=True)
api_key = DEFAULT_KEY if use_default_api else st.sidebar.text_input("Egen OpenAI API-nyckel", type="password")

if not api_key:
    st.warning("⚠️ Ange eller aktivera en OpenAI-nyckel.")
    st.stop()

client = OpenAI(api_key=api_key)

# ---------- GENERERA VARIATIONER ----------
def generate_variations(prompt: str) -> list[str]:
    """Skapa 10 naturliga variationer av prompten."""
    messages = [
        {"role": "system", "content": "Return ONLY JSON. Format: {\"variations\": [\"...\", ...]}"},
        {"role": "user", "content": f"Generate 10 natural language variations (same language) of this query:\n\n{prompt}\n\nKeep the same intent, concise, no duplicates."}
    ]
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        return data["variations"]
    except Exception:
        resp = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
        raw = resp.choices[0].message.content or ""
        m_obj = re.search(r'\{\s*"variations"\s*:\s*\[.*?\]\s*\}', raw, re.DOTALL)
        if m_obj:
            try:
                data = json.loads(m_obj.group(0))
                return data["variations"]
            except:
                pass
        lines = [l.strip("-• ").strip() for l in raw.splitlines() if l.strip()]
        return lines[:10]


# ---------- PLAYWRIGHT HELPERS ----------
PROFILE_PATH = Path("playwright_profile")
PROFILE_PATH.mkdir(exist_ok=True)

def ensure_logged_in():
    """Starta browser om användaren inte redan loggat in."""
    marker = PROFILE_PATH / "LoginComplete.txt"
    if marker.exists():
        return True  # redan inloggad

    st.warning("Ingen sparad inloggning hittad. Vi öppnar ett fönster så du kan logga in i ChatGPT.")
    st.info("1️⃣ Logga in i fönstret som öppnas. \n2️⃣ Tryck sedan på knappen ✅ 'Jag är inloggad' här i Streamlit.")

    if st.button("Öppna inloggningsfönster"):
        with sync_playwright() as p:
            p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_PATH),
                headless=False,
                args=["--start-maximized"],
            )
        st.success("✅ Fönster öppnat. Logga in där!")

    # Vänta på bekräftelse
    if st.button("✅ Jag är inloggad, fortsätt"):
        marker.write_text("ok")
        st.success("Inloggning markerad som klar! Du kan nu köra analys.")
        st.stop()


def get_search_queries_single_session(variations):
    """Kör alla prompts i samma persistent browser-profil och hämtar search_model_query."""
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_PATH),
            headless=False,  # nu headless eftersom du redan loggat in
        )

        page = browser.new_page()
        page.goto("https://chat.openai.com")
        time.sleep(3)

        for var in variations:
            try:
                headers = {
                    "authority": "chat.openai.com",
                    "accept": "text/event-stream",
                    "content-type": "application/json",
                }
                data = {
                    "action": "next",
                    "messages": [{
                        "id": "1",
                        "author": {"role": "user"},
                        "content": {"content_type": "text", "parts": [var]},
                        "metadata": {},
                    }],
                    "model": "gpt-4o",
                    "conversation_mode": {"kind": "web_browser"},
                    "parent_message_id": "0"
                }

                response = page.request.post(
                    "https://chat.openai.com/backend-api/conversation",
                    data=json.dumps(data),
                    headers=headers
                )

                text = response.text()
                matches = re.findall(r'"search_model_query":"(.*?)"', text)
                results.append({
                    "Promptvariation": var,
                    "search_model_query": matches[-1] if matches else "(Ingen search_model_query hittad)"
                })
            except Exception as e:
                results.append({"Promptvariation": var, "search_model_query": f"Fel: {e}"})

        browser.close()
    return results


# ---------- UI ----------
prompt = st.text_area("📝 Huvudprompt:", "Jag är i behov av en bra redovisningsbyrå i Stockholmsområdet")

if st.button("Kör analys"):
    ensure_logged_in()  # säkerställ att login finns

    st.info("🔄 Genererar variationer...")
    try:
        variations = generate_variations(prompt)
    except Exception as e:
        st.error(f"Fel vid generering: {e}")
        st.stop()

    if not variations:
        st.error("Inga variationer genererade.")
        st.stop()

    st.success("✅ 10 variationer skapade!")
    st.write(f"Exempel: {variations[:3]}")

    st.info("🕵️‍♂️ Hämtar search_model_query för varje variation...")
    progress = st.progress(0)

    results = get_search_queries_single_session(variations)
    for i in range(len(results)):
        progress.progress((i + 1) / len(results))

    st.success("✅ Klar!")
    st.dataframe(results, use_container_width=True)

    st.download_button(
        "⬇️ Ladda ner resultat som JSON",
        data=json.dumps(results, indent=2, ensure_ascii=False),
        file_name="search_queries.json",
        mime="application/json",
    )

    st.caption("Byggd av Edvin & Hugo ⚡ (persistent login-mode)")
