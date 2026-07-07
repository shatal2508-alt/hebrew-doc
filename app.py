import base64
import json

import streamlit as st
import streamlit.components.v1 as components
from anthropic import Anthropic

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document
except ImportError:
    Document = None


MODEL_NAME = "claude-sonnet-5"  # Claude Sonnet 5 (claude-3-5-sonnet הוצא משימוש ב-API)
MAX_TOKENS = 4096
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

st.set_page_config(
    page_title="עוזר סיכום מסמכים",
    page_icon="📝",
    layout="centered",
)

# עיצוב מקצועי ונקי, עם RTL ממוקד רק לאזור התוכן (לא לרכיבי המערכת הפנימיים
# של Streamlit — פנייה גורפת אליהם היא מה שגרמה לאייקונים/טקסט "לקפוץ" ולהתנגש).
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;500;600;700&display=swap');

    html, body, [data-testid="stAppViewContainer"] {
        font-family: 'Assistant', sans-serif;
    }

    /* מסתירים מיתוג ברירת מחדל של Streamlit לצורך מראה נקי */
    #MainMenu, footer, [data-testid="stToolbar"] {
        visibility: hidden;
    }

    [data-testid="stAppViewContainer"] .main .block-container {
        direction: rtl;
        text-align: right;
        max-width: 760px;
        padding-top: 2.5rem;
        padding-bottom: 3rem;
    }

    .stTextArea textarea, .stTextInput input, .stRadio, .stFileUploader {
        direction: rtl;
        text-align: right;
    }

    h1, h2, h3 {
        font-weight: 700;
    }

    .stButton button {
        width: 100%;
        border-radius: 8px;
        font-weight: 600;
        padding: 0.6rem 1rem;
    }

    [data-testid="stFileUploaderDropzone"] {
        direction: rtl;
    }

    [data-testid="stChatInput"] textarea {
        direction: rtl;
        text-align: right;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def init_session_state() -> None:
    """מאתחל את מפתחות ה-session_state שבהם נשמר כל המידע הזמני של הסשן.

    כל הערכים חיים אך ורק בזיכרון הסשן של Streamlit: רענון הדף או סגירת
    הלשונית פותחים חיבור/סשן חדש ומאפסים אותם לחלוטין, ללא כל שמירה קבועה.
    """
    defaults = {
        "merged_text": "",   # "תיבת האם" - הטקסט המלא והממוזג מכל הקבצים שהועלו
        "summary": "",       # הסיכום הממוקד שנוצר מתוך תיבת האם
        "qa_history": [],    # רשימת (שאלה, תשובה) של שאלות ההמשך על הסיכום
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_session_state() -> None:
    st.session_state.merged_text = ""
    st.session_state.summary = ""
    st.session_state.qa_history = []


def render_copy_button(text: str, key: str, label: str = "📋 העתק טקסט") -> None:
    """מרנדר כפתור מעוצב להעתקת טקסט ללוח (clipboard) של המכשיר.

    משתמש ב-navigator.clipboard.writeText עם נפילה חזרה ל-execCommand,
    כדי שיעבוד גם בדפדפני מובייל ישנים יותר.
    """
    safe_text = json.dumps(text)
    button_id = f"copy-btn-{key}"
    html_code = f"""
    <div style="direction: rtl; text-align: right; font-family: 'Assistant', sans-serif;">
      <button id="{button_id}" style="
          width: 100%;
          border-radius: 8px;
          font-weight: 600;
          padding: 0.5rem 1rem;
          border: 1px solid rgba(49, 51, 63, 0.2);
          background-color: transparent;
          color: inherit;
          cursor: pointer;
          font-size: 0.95rem;
      ">{label}</button>
    </div>
    <script>
      (function() {{
        const btn = document.getElementById("{button_id}");
        const originalLabel = btn.textContent;
        btn.addEventListener("click", async function() {{
          const text = {safe_text};
          try {{
            await navigator.clipboard.writeText(text);
          }} catch (err) {{
            const textarea = document.createElement("textarea");
            textarea.value = text;
            textarea.style.position = "fixed";
            textarea.style.opacity = "0";
            document.body.appendChild(textarea);
            textarea.focus();
            textarea.select();
            try {{ document.execCommand("copy"); }} catch (e) {{}}
            document.body.removeChild(textarea);
          }}
          btn.textContent = "✅ הועתק!";
          setTimeout(function() {{ btn.textContent = originalLabel; }}, 1500);
        }});
      }})();
    </script>
    """
    components.html(html_code, height=45)


def get_api_key() -> str:
    try:
        secret_key = st.secrets["ANTHROPIC_API_KEY"]
    except Exception:  # noqa: BLE001 - st.secrets raises when no secrets file exists
        secret_key = ""

    if secret_key:
        return secret_key.strip()

    with st.expander("🔧 הגדרות: הזנת מפתח API", expanded=False):
        key_input = st.text_input(
            "מפתח API של Anthropic",
            type="password",
            help="המפתח נשמר רק לסשן הנוכחי ואינו נשלח לשום מקום מלבד Anthropic.",
        )
    return key_input.strip()


def extract_text_from_pdf(uploaded_file) -> str:
    if PdfReader is None:
        st.error("הספרייה pypdf אינה מותקנת. הריצו: pip install pypdf")
        st.stop()
    reader = PdfReader(uploaded_file)
    pages_text = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages_text).strip()


def extract_text_from_docx(uploaded_file) -> str:
    if Document is None:
        st.error("הספרייה python-docx אינה מותקנת. הריצו: pip install python-docx")
        st.stop()
    document = Document(uploaded_file)
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text.strip())
    return "\n".join(parts).strip()


def image_to_base64(uploaded_file) -> tuple[str, str]:
    extension = uploaded_file.name.rsplit(".", 1)[-1].lower()
    media_type_map = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }
    media_type = media_type_map.get(extension, "image/png")
    raw_bytes = uploaded_file.getvalue()
    encoded = base64.standard_b64encode(raw_bytes).decode("utf-8")
    return encoded, media_type


def extract_text_from_image(api_key: str, uploaded_file) -> str:
    """מבקש מ-Claude לתמלל/לתאר את תוכן התמונה, כדי שגם קבצי תמונה יזינו
    את אותה תיבת טקסט מרכזית כמו PDF ו-Word."""
    client = Anthropic(api_key=api_key)
    encoded, media_type = image_to_base64(uploaded_file)
    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": encoded},
                    },
                    {
                        "type": "text",
                        "text": (
                            "תמלל ותאר במדויק ובעברית את כל הטקסט והתוכן הרלוונטי "
                            "המופיע בתמונה הזו, ללא פרשנות או תוספות משלך."
                        ),
                    },
                ],
            }
        ],
    )
    return "".join(block.text for block in response.content if block.type == "text").strip()


def extract_text_from_upload(api_key: str, uploaded_file) -> str:
    """מחלץ טקסט מקובץ יחיד בהתאם לסיומת שלו (PDF / Word / תמונה)."""
    name = uploaded_file.name
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    if extension == "pdf":
        return extract_text_from_pdf(uploaded_file)
    if extension == "docx":
        return extract_text_from_docx(uploaded_file)
    if extension in IMAGE_EXTENSIONS:
        return extract_text_from_image(api_key, uploaded_file)
    raise ValueError(f"סוג קובץ לא נתמך: .{extension}")


HEBREW_QUALITY_GUIDELINES = (
    "עליך לכתוב אך ורק בעברית תקנית, רהוטה, אקדמית וטבעית לחלוטין (רמת שפת אם גבוהה). "
    "הימנע לחלוטין מתרגום מילולי מאנגלית (Literal translation) או מניסוחים שנשמעים כמו תרגום מכונה. "
    "השתמש בפיסוק נכון, במשפטים מנוסחים היטב, בחלוקה נכונה לפסקאות, ובזרימת קריאה חלקה, "
    "ללא טעויות דקדוק או הגהה."
)


def build_summary_system_prompt(focus: str) -> str:
    return (
        "אתה עוזר כתיבה מומחה בעברית תקנית וגבוהה. "
        "המשימה שלך היא לקרוא את התוכן שיסופק לך (שעשוי להיות ממוזג ממספר מסמכים) "
        "ולכתוב ממנו סיכום בעברית רהוטה, תקנית ומדויקת, ללא שום שגיאות כתיב או ניקוד שגוי. "
        "התמקד אך ורק בהיבט הבא שביקש המשתמש, והשמט כל מידע שאינו רלוונטי אליו: "
        f"\"{focus}\". "
        "אם התוכן אינו כולל מידע רלוונטי לנושא המבוקש, ציין זאת בבירור בעברית. "
        "כתוב בסגנון ברור, קולח ומקצועי, בפסקאות מסודרות.\n\n"
        f"{HEBREW_QUALITY_GUIDELINES}"
    )


def build_followup_system_prompt() -> str:
    return (
        "אתה עוזר כתיבה מומחה בעברית תקנית וגבוהה. "
        "בהמשך תקבל את התוכן המלא של המסמכים שהועלו, את הסיכום הממוקד שכבר הוכן מהם, "
        "ולבסוף שאלת המשך של המשתמשת. "
        "ענה על השאלה בעברית ברורה ומדויקת, בהתבסס אך ורק על התוכן המלא ועל הסיכום שסופקו לך. "
        "אם התשובה לשאלה אינה נמצאת במידע שסופק, ציין זאת בבירור במקום לנחש.\n\n"
        f"{HEBREW_QUALITY_GUIDELINES}"
    )


def call_claude_summary(api_key: str, focus: str, merged_text: str) -> str:
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=build_summary_system_prompt(focus),
        messages=[
            {"role": "user", "content": f"להלן התוכן לסיכום:\n\n{merged_text}"},
        ],
    )
    return "".join(block.text for block in response.content if block.type == "text").strip()


def call_claude_followup(api_key: str, merged_text: str, summary: str, question: str) -> str:
    client = Anthropic(api_key=api_key)
    user_message = (
        f"התוכן המלא של המסמכים שהועלו:\n\n{merged_text}\n\n"
        f"---\n\nהסיכום שכבר הוכן מהתוכן:\n\n{summary}\n\n"
        f"---\n\nשאלת ההמשך של המשתמשת:\n{question}"
    )
    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=build_followup_system_prompt(),
        messages=[{"role": "user", "content": user_message}],
    )
    return "".join(block.text for block in response.content if block.type == "text").strip()


init_session_state()

st.title("📝 עוזר סיכום מסמכים")

api_key = get_api_key()

if not api_key:
    st.warning("🔑 כדי להתחיל, יש להזין מפתח API של Anthropic בתפריט 'הגדרות' שלמעלה.")
    st.stop()

focus = st.text_input("במה להתמקד בסיכום?", placeholder="לדוגמה: המסקנות העיקריות וההמלצות בלבד")

input_mode = st.radio("בחרו את אופן הקלט:", ["העלאת קבצים", "הזנת טקסט"], horizontal=True)

uploaded_files = None
manual_text = ""

if input_mode == "העלאת קבצים":
    uploaded_files = st.file_uploader(
        "העלו קובץ אחד או יותר: PDF, Word (docx) או תמונה (png/jpg/jpeg/webp)",
        type=["pdf", "docx", "png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
    )
else:
    manual_text = st.text_area("הזינו את הטקסט לסיכום:", height=250)

col_generate, col_reset = st.columns([3, 1])
generate = col_generate.button("צור סיכום", type="primary")
reset_clicked = col_reset.button("🗑️ נקה הכל")

if reset_clicked:
    reset_session_state()
    st.rerun()

if generate:
    if not focus.strip():
        st.error("יש לציין במה להתמקד בסיכום.")
        st.stop()

    merged_parts = []

    if input_mode == "העלאת קבצים":
        if not uploaded_files:
            st.error("יש להעלות לפחות קובץ אחד.")
            st.stop()

        with st.spinner(f"מחלץ תוכן מ-{len(uploaded_files)} קבצים..."):
            for uploaded_file in uploaded_files:
                try:
                    extracted = extract_text_from_upload(api_key, uploaded_file)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"אירעה שגיאה בחילוץ תוכן מהקובץ '{uploaded_file.name}': {exc}")
                    st.stop()

                if not extracted:
                    st.warning(
                        f"לא נמצא תוכן הניתן לחילוץ בקובץ '{uploaded_file.name}' "
                        "(ייתכן שמדובר ב-PDF סרוק ללא טקסט). הקובץ דולג."
                    )
                    continue

                merged_parts.append(f"### קובץ: {uploaded_file.name}\n\n{extracted}")

        if not merged_parts:
            st.error("לא נמצא תוכן הניתן לחילוץ באף אחד מהקבצים שהועלו.")
            st.stop()
    else:
        if not manual_text.strip():
            st.error("יש להזין טקסט לסיכום.")
            st.stop()
        merged_parts.append(manual_text.strip())

    merged_text = "\n\n---\n\n".join(merged_parts)

    with st.spinner("Claude מכין את הסיכום..."):
        try:
            summary = call_claude_summary(api_key, focus.strip(), merged_text)
        except Exception as exc:  # noqa: BLE001
            st.error(f"אירעה שגיאה בקריאה ל-API של Anthropic: {exc}")
            st.stop()

    st.session_state.merged_text = merged_text
    st.session_state.summary = summary
    st.session_state.qa_history = []

if st.session_state.summary:
    st.divider()
    st.subheader("📄 הסיכום")
    with st.container(border=True):
        st.markdown(st.session_state.summary)
    render_copy_button(st.session_state.summary, key="summary")
    st.download_button(
        "הורידו את הסיכום כקובץ טקסט",
        data=st.session_state.summary.encode("utf-8"),
        file_name="summary.txt",
        mime="text/plain",
    )

    st.divider()
    st.subheader("💬 שאלות המשך על הסיכום")
    st.caption("אפשר לשאול הבהרות נוספות על סמך כל התוכן שהועלה ועל סמך הסיכום שנוצר.")

    for i, (question, answer) in enumerate(st.session_state.qa_history):
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            st.markdown(answer)
            render_copy_button(answer, key=f"qa-{i}")

    followup_question = st.chat_input("שאלו שאלה נוספת או בקשו הבהרה על הסיכום...")

    if followup_question:
        with st.chat_message("user"):
            st.markdown(followup_question)

        with st.spinner("Claude מכין תשובה..."):
            try:
                answer = call_claude_followup(
                    api_key,
                    st.session_state.merged_text,
                    st.session_state.summary,
                    followup_question,
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"אירעה שגיאה בקריאה ל-API של Anthropic: {exc}")
                st.stop()

        with st.chat_message("assistant"):
            st.markdown(answer)
            render_copy_button(answer, key=f"qa-{len(st.session_state.qa_history)}")

        st.session_state.qa_history.append((followup_question, answer))
