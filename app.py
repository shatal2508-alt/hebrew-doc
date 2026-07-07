import base64
import io
import os

import streamlit as st
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
    </style>
    """,
    unsafe_allow_html=True,
)

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


def build_system_prompt(focus: str) -> str:
    return (
        "אתה עוזר כתיבה מומחה בעברית תקנית וגבוהה. "
        "המשימה שלך היא לקרוא את התוכן שיסופק לך (טקסט, מסמך או תמונה) "
        "ולכתוב ממנו סיכום בעברית רהוטה, תקנית ומדויקת, ללא שום שגיאות כתיב או ניקוד שגוי. "
        "התמקד אך ורק בהיבט הבא שביקש המשתמש, והשמט כל מידע שאינו רלוונטי אליו: "
        f"\"{focus}\". "
        "אם התוכן אינו כולל מידע רלוונטי לנושא המבוקש, ציין זאת בבירור בעברית. "
        "כתוב בסגנון ברור, קולח ומקצועי, בפסקאות מסודרות."
    )


def call_claude(api_key: str, focus: str, text_content: str = None, image_data: tuple = None) -> str:
    client = Anthropic(api_key=api_key)
    system_prompt = build_system_prompt(focus)

    content = []
    if image_data:
        encoded, media_type = image_data
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": encoded,
                },
            }
        )
        content.append({"type": "text", "text": "אנא סכם את התמונה בהתאם להנחיות שקיבלת."})
    else:
        content.append(
            {
                "type": "text",
                "text": f"להלן התוכן לסיכום:\n\n{text_content}",
            }
        )

    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": content}],
    )
    return "".join(block.text for block in response.content if block.type == "text").strip()


st.title("📝 עוזר סיכום מסמכים")

api_key = get_api_key()

if not api_key:
    st.warning("🔑 כדי להתחיל, יש להזין מפתח API של Anthropic בתפריט 'הגדרות' שלמעלה.")
    st.stop()

focus = st.text_input("במה להתמקד בסיכום?", placeholder="לדוגמה: המסקנות העיקריות וההמלצות בלבד")

input_mode = st.radio("בחרו את אופן הקלט:", ["העלאת קובץ", "הזנת טקסט"], horizontal=True)

uploaded_file = None
manual_text = ""

if input_mode == "העלאת קובץ":
    uploaded_file = st.file_uploader(
        "העלו קובץ PDF, Word (docx) או תמונה (png/jpg/jpeg/webp)",
        type=["pdf", "docx", "png", "jpg", "jpeg", "webp"],
    )
else:
    manual_text = st.text_area("הזינו את הטקסט לסיכום:", height=250)

generate = st.button("צור סיכום", type="primary")

if generate:
    if not focus.strip():
        st.error("יש לציין במה להתמקד בסיכום.")
        st.stop()

    text_content = None
    image_data = None

    if input_mode == "העלאת קובץ":
        if uploaded_file is None:
            st.error("יש להעלות קובץ.")
            st.stop()

        file_name = uploaded_file.name.lower()
        with st.spinner("מחלץ תוכן מהקובץ..."):
            if file_name.endswith(".pdf"):
                text_content = extract_text_from_pdf(uploaded_file)
                if not text_content:
                    st.warning("לא נמצא טקסט הניתן לחילוץ מה-PDF (ייתכן שמדובר בסריקה). נסו קובץ תמונה במקום.")
                    st.stop()
            elif file_name.endswith(".docx"):
                text_content = extract_text_from_docx(uploaded_file)
                if not text_content:
                    st.warning("לא נמצא טקסט במסמך ה-Word.")
                    st.stop()
            else:
                image_data = image_to_base64(uploaded_file)
    else:
        if not manual_text.strip():
            st.error("יש להזין טקסט לסיכום.")
            st.stop()
        text_content = manual_text.strip()

    with st.spinner("Claude מכין את הסיכום..."):
        try:
            summary = call_claude(api_key, focus.strip(), text_content=text_content, image_data=image_data)
        except Exception as exc:  # noqa: BLE001
            st.error(f"אירעה שגיאה בקריאה ל-API של Anthropic: {exc}")
            st.stop()

    st.divider()
    st.subheader("📄 הסיכום")
    with st.container(border=True):
        st.markdown(summary)
    st.download_button(
        "הורידו את הסיכום כקובץ טקסט",
        data=summary.encode("utf-8"),
        file_name="summary.txt",
        mime="text/plain",
    )
