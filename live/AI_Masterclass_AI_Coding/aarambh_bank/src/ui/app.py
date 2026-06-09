"""Aarambh Bank — Streamlit UI.

Run from project root:  streamlit run src/ui/app.py
"""

import html
import os
import sys
from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Bootstrap — add project root to sys.path and load .env
# ---------------------------------------------------------------------------
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
load_dotenv(os.path.join(_ROOT, ".env"))

# Feature imports (after path setup)
from src.features.account import (  # noqa: E402
    fun_create_account,
    fun_get_account,
    fun_mask_account_number,
)
from src.features.auth import fun_login, fun_register  # noqa: E402
from src.features.chat import fun_create_session  # noqa: E402
from src.features.dashboard import fun_get_dashboard_data  # noqa: E402
from src.features.deposit import fun_deposit  # noqa: E402
from src.features.statement import fun_generate_csv, fun_get_statement  # noqa: E402
from src.features.withdraw import fun_withdraw  # noqa: E402

# ---------------------------------------------------------------------------
# Design system constants
# ---------------------------------------------------------------------------
GREEN = "#00E676"
PURPLE = "#8A5CF6"
PINK = "#FF2D95"

# ---------------------------------------------------------------------------
# Page config — must be the first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Aarambh Bank",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ===========================================================================
# CSS injection
# ===========================================================================


def fun_inject_css() -> None:
    """Inject the Aarambh Bank design system CSS.

    Applies solid colours (no gradients), white background, black text,
    purple sidebar, green primary buttons, and WhatsApp-style chat bubbles.

    Returns:
        None
    """
    st.markdown(
        f"""
        <style>
        /* ── Global ── */
        .stApp {{
            background-color: #FFFFFF;
            color: #000000;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }}
        h1, h2, h3, h4, h5, h6, p, label, div {{
            color: #000000;
        }}

        /* ── Sidebar ── */
        [data-testid="stSidebar"] > div:first-child {{
            background-color: {PURPLE};
        }}
        [data-testid="stSidebar"] .stMarkdown p,
        [data-testid="stSidebar"] .stMarkdown h1,
        [data-testid="stSidebar"] .stMarkdown h2,
        [data-testid="stSidebar"] .stMarkdown h3,
        [data-testid="stSidebar"] label {{
            color: #FFFFFF !important;
        }}
        [data-testid="stSidebarNav"] {{ display: none; }}

        /* ── Buttons ── */
        .stButton > button {{
            background-color: {GREEN};
            color: #000000;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            transition: background-color 0.15s;
        }}
        .stButton > button:hover {{
            background-color: #00C853;
            color: #000000;
            border: none;
        }}
        .stButton > button:active {{
            background-color: #00BFA5;
            border: none;
        }}

        /* ── Sidebar logout button — pink accent ── */
        [data-testid="stSidebar"] .stButton > button {{
            background-color: rgba(255,255,255,0.15);
            color: #FFFFFF;
            border: 1px solid rgba(255,255,255,0.3);
        }}
        [data-testid="stSidebar"] .stButton > button:hover {{
            background-color: {PINK};
            color: #000000;
            border-color: {PINK};
        }}

        /* ── Metric cards ── */
        .ab-card {{
            background: #FFFFFF;
            border-radius: 12px;
            padding: 1.2rem 1.4rem;
            box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            margin-bottom: 1rem;
            border-left: 5px solid {PURPLE};
        }}
        .ab-card-green  {{ border-left-color: {GREEN};  }}
        .ab-card-pink   {{ border-left-color: {PINK};   }}
        .ab-card-label  {{
            font-size: 0.72rem;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            margin-bottom: 0.3rem;
        }}
        .ab-card-value  {{
            font-size: 1.55rem;
            font-weight: 700;
            color: #000000;
            line-height: 1.2;
        }}
        .ab-card-sub    {{
            font-size: 0.83rem;
            color: #555;
            margin-top: 0.3rem;
        }}

        /* ── Section header ── */
        .ab-section {{
            color: {PURPLE};
            font-size: 1.05rem;
            font-weight: 700;
            margin: 1.6rem 0 0.7rem;
            padding-bottom: 0.3rem;
            border-bottom: 2px solid {PURPLE};
        }}

        /* ── Page title ── */
        .ab-title {{
            font-size: 1.9rem;
            font-weight: 800;
            color: {PURPLE};
            margin-bottom: 1.4rem;
        }}

        /* ── Type badges ── */
        .badge-credit {{
            background: #E8F5E9; color: #1B5E20;
            border-radius: 10px; padding: 2px 9px;
            font-size: 0.75rem; font-weight: 700;
        }}
        .badge-debit {{
            background: #FCE4EC; color: #880E4F;
            border-radius: 10px; padding: 2px 9px;
            font-size: 0.75rem; font-weight: 700;
        }}

        /* ── Auth form wrapper ── */
        .ab-auth-wrap {{
            background: #FFFFFF;
            border-radius: 16px;
            padding: 2.5rem 2rem;
            box-shadow: 0 4px 28px rgba(0,0,0,0.10);
        }}

        /* ── Chat ── */
        .ab-chat-box {{
            height: 440px;
            overflow-y: auto;
            padding: 1rem 1.2rem;
            background: #F8F8F8;
            border-radius: 12px;
            border: 1px solid #E0E0E0;
            margin-bottom: 0.8rem;
        }}
        .ab-chat-row-user      {{ display:flex; justify-content:flex-end;  margin:6px 0; }}
        .ab-chat-row-assistant {{ display:flex; justify-content:flex-start; margin:6px 0; }}
        .ab-bubble-user {{
            background-color: {GREEN};
            color: #000000;
            border-radius: 18px 18px 4px 18px;
            padding: 9px 15px;
            max-width: 68%;
            font-size: 0.92rem;
            line-height: 1.5;
            word-wrap: break-word;
        }}
        .ab-bubble-assistant {{
            background-color: #FFFFFF;
            color: #000000;
            border: 2px solid {PURPLE};
            border-radius: 18px 18px 18px 4px;
            padding: 9px 15px;
            max-width: 68%;
            font-size: 0.92rem;
            line-height: 1.5;
            word-wrap: break-word;
        }}

        /* ── All native inputs — force white bg / black text ── */
        input, textarea, select {{
            background-color: #FFFFFF !important;
            color: #000000 !important;
        }}

        /* ── Streamlit text / number input wrappers ── */
        .stTextInput > div > div > input,
        .stNumberInput > div > div > input {{
            background-color: #FFFFFF !important;
            color: #000000 !important;
            border-radius: 8px;
            border: 1.5px solid #CCCCCC;
        }}
        .stTextInput > div > div > input:focus,
        .stNumberInput > div > div > input:focus {{
            border-color: {PURPLE};
            box-shadow: 0 0 0 2px rgba(138,92,246,0.18);
        }}

        /* ── Selectbox button (visible pill) ── */
        .stSelectbox > div > div,
        .stSelectbox > div > div > div,
        [data-baseweb="select"] > div {{
            background-color: #FFFFFF !important;
            color: #000000 !important;
            border: 1.5px solid #CCCCCC !important;
            border-radius: 8px !important;
        }}
        [data-baseweb="select"] svg {{
            fill: #000000 !important;
        }}

        /* ── Dropdown list (popover / menu portal) ── */
        [data-baseweb="popover"],
        [data-baseweb="popover"] > div,
        [data-baseweb="menu"],
        [data-baseweb="menu"] ul,
        [data-baseweb="menu"] li,
        [role="listbox"],
        [role="option"] {{
            background-color: #FFFFFF !important;
            color: #000000 !important;
        }}
        [role="option"]:hover,
        [role="option"][aria-selected="true"] {{
            background-color: #EDE9FE !important;
            color: #000000 !important;
        }}

        /* ── Date input ── */
        .stDateInput > div > div > input {{
            background-color: #FFFFFF !important;
            color: #000000 !important;
        }}

        /* ── Multiselect tags ── */
        [data-baseweb="tag"] {{
            background-color: {PURPLE} !important;
            color: #FFFFFF !important;
        }}

        /* ── Any stray dark backgrounds from base-web ── */
        [data-baseweb="base-input"] {{
            background-color: #FFFFFF !important;
            color: #000000 !important;
        }}

        /* ── Hide Streamlit chrome ── */
        #MainMenu {{ visibility: hidden; }}
        footer     {{ visibility: hidden; }}
        header     {{ visibility: hidden; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ===========================================================================
# Helpers
# ===========================================================================


def fun_fmt_inr(amount) -> str:
    """Format a Decimal or numeric value as an INR amount string.

    Args:
        amount: Monetary value (Decimal or numeric).

    Returns:
        str: Formatted string, e.g. 'INR 1,234.56'.
    """
    try:
        return f"INR {Decimal(str(amount)):,.2f}"
    except Exception:
        return f"INR {amount}"


def fun_init_session() -> None:
    """Initialise session state keys with defaults if absent.

    Returns:
        None
    """
    defaults: dict = {
        "logged_in": False,
        "user_id": None,
        "username": None,
        "page": "login",
        "account_id": None,
        "chat_session": None,
        "chat_messages": [],
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def fun_go(page: str) -> None:
    """Navigate to a named page and re-render.

    Args:
        page: Target page key.

    Returns:
        None
    """
    st.session_state.page = page
    st.rerun()


def fun_card(label: str, value: str, sub: str = "", variant: str = "") -> None:
    """Render a styled summary card.

    Args:
        label:   Small uppercase heading.
        value:   Primary large-text value.
        sub:     Optional subtitle.
        variant: CSS variant class suffix (e.g. 'green', 'pink').

    Returns:
        None
    """
    sub_html = f'<div class="ab-card-sub">{sub}</div>' if sub else ""
    variant_cls = f"ab-card-{variant}" if variant else ""
    st.markdown(
        f'<div class="ab-card {variant_cls}">'
        f'<div class="ab-card-label">{label}</div>'
        f'<div class="ab-card-value">{value}</div>'
        f"{sub_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def fun_section(title: str) -> None:
    """Render a purple section divider heading.

    Args:
        title: Section heading text.

    Returns:
        None
    """
    st.markdown(f'<div class="ab-section">{title}</div>', unsafe_allow_html=True)


def fun_page_title(title: str) -> None:
    """Render the page title in purple.

    Args:
        title: Page heading text.

    Returns:
        None
    """
    st.markdown(f'<div class="ab-title">{title}</div>', unsafe_allow_html=True)


def fun_ensure_account() -> bool:
    """Ensure account_id is set in session state, fetching it if necessary.

    Returns:
        bool: True if an account exists and account_id is set.
    """
    if st.session_state.account_id:
        return True
    acct = fun_get_account(st.session_state.user_id)
    if acct:
        st.session_state.account_id = acct["id"]
        return True
    return False


# ===========================================================================
# Sidebar
# ===========================================================================


def fun_show_sidebar() -> None:
    """Render the authenticated-user navigation sidebar.

    Returns:
        None
    """
    with st.sidebar:
        st.markdown(
            "<h2 style='color:#FFF;margin:0 0 4px'>🏦 Aarambh Bank</h2>"
            f"<p style='color:#E0D8FF;font-size:0.82rem;margin:0 0 16px'>"
            f"Hello, {st.session_state.username}</p>",
            unsafe_allow_html=True,
        )
        st.markdown("---")

        nav_items = [
            ("dashboard", "🏠  Dashboard"),
            ("deposit",   "⬆️  Deposit"),
            ("withdraw",  "⬇️  Withdraw"),
            ("statement", "📋  Statement"),
            ("chat",      "💬  Chat Assistant"),
        ]
        for key, label in nav_items:
            if st.button(label, key=f"nav_{key}", use_container_width=True):
                fun_go(key)

        st.markdown("---")
        if st.button("Logout", key="nav_logout", use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()


# ===========================================================================
# Auth pages
# ===========================================================================


def fun_show_login() -> None:
    """Render the login page.

    Returns:
        None
    """
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        st.markdown(
            f"<div style='text-align:center;margin:2.5rem 0 1.5rem'>"
            f"<h1 style='color:{PURPLE};font-size:2.2rem'>🏦 Aarambh Bank</h1>"
            f"<p style='color:#666'>Your modern banking companion</p>"
            f"</div>",
            unsafe_allow_html=True,
        )

        with st.form("login_form"):
            st.markdown(
                f"<h3 style='color:{PURPLE};margin-bottom:1rem'>Sign In</h3>",
                unsafe_allow_html=True,
            )
            username = st.text_input("Username", placeholder="Enter username")
            user_pw = st.text_input(
                "Password", type="password", placeholder="Enter password"
            )
            submitted = st.form_submit_button(
                "Login", use_container_width=True
            )

        if submitted:
            if not username or not user_pw:
                st.error("Please fill in all fields.")
            else:
                result = fun_login(username, user_pw)
                if result["ok"]:
                    st.session_state.logged_in = True
                    st.session_state.user_id = result["user_id"]
                    st.session_state.username = result["username"]
                    acct = fun_get_account(result["user_id"])
                    if acct is None:
                        cr = fun_create_account(result["user_id"])
                        if cr["ok"]:
                            st.session_state.account_id = cr["account_id"]
                    else:
                        st.session_state.account_id = acct["id"]
                    fun_go("dashboard")
                else:
                    st.error(result["error"])

        st.markdown(
            "<p style='text-align:center;color:#666;margin:1rem 0 0.5rem'>"
            "New to Aarambh Bank?</p>",
            unsafe_allow_html=True,
        )
        if st.button(
            "Create Account", key="go_register", use_container_width=True
        ):
            fun_go("register")


def fun_show_register() -> None:
    """Render the registration page.

    Returns:
        None
    """
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        st.markdown(
            f"<div style='text-align:center;margin:2.5rem 0 1.5rem'>"
            f"<h1 style='color:{PURPLE};font-size:2.2rem'>🏦 Aarambh Bank</h1>"
            f"</div>",
            unsafe_allow_html=True,
        )

        with st.form("register_form"):
            st.markdown(
                f"<h3 style='color:{PURPLE};margin-bottom:1rem'>Create Account</h3>",
                unsafe_allow_html=True,
            )
            username = st.text_input("Username", placeholder="Choose a username")
            email = st.text_input("Email", placeholder="your@email.com")
            phone = st.text_input("Phone", placeholder="Digits only, e.g. 9876543210")
            reg_pw = st.text_input(
                "Password", type="password", placeholder="Min 8 characters"
            )
            submitted = st.form_submit_button(
                "Register", use_container_width=True
            )

        if submitted:
            result = fun_register(username, email, phone, reg_pw)
            if result["ok"]:
                st.success("Registration successful! Please log in.")
                fun_go("login")
            else:
                st.error(result["error"])

        st.markdown(
            "<p style='text-align:center;color:#666;margin:1rem 0 0.5rem'>"
            "Already have an account?</p>",
            unsafe_allow_html=True,
        )
        if st.button("Back to Login", key="go_login", use_container_width=True):
            fun_go("login")


# ===========================================================================
# Dashboard
# ===========================================================================


def fun_show_dashboard() -> None:
    """Render the account summary dashboard with cards and recent transactions.

    Returns:
        None
    """
    data = fun_get_dashboard_data(st.session_state.user_id)

    if data is None:
        st.info("Setting up your account...")
        cr = fun_create_account(st.session_state.user_id)
        if cr["ok"]:
            st.session_state.account_id = cr["account_id"]
            st.rerun()
        else:
            st.error(cr["error"])
        return

    if st.session_state.account_id is None:
        acct = fun_get_account(st.session_state.user_id)
        if acct:
            st.session_state.account_id = acct["id"]

    fun_page_title(f"Welcome back, {data['username']}")

    # ── Summary cards ──────────────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    with c1:
        fun_card("Current Balance", fun_fmt_inr(data["balance"]), variant="green")
    with c2:
        fun_card(
            "Account Number",
            data["masked_account_number"],
            sub="Last 4 digits shown",
        )
    with c3:
        fun_card("Phone", data["phone"], sub=data["email"])

    # ── Quick actions ──────────────────────────────────────────────────────
    fun_section("Quick Actions")
    qa1, qa2, qa3, qa4 = st.columns(4)
    with qa1:
        if st.button("⬆️ Deposit", key="qa_dep", use_container_width=True):
            fun_go("deposit")
    with qa2:
        if st.button("⬇️ Withdraw", key="qa_wd", use_container_width=True):
            fun_go("withdraw")
    with qa3:
        if st.button("📋 Statement", key="qa_stmt", use_container_width=True):
            fun_go("statement")
    with qa4:
        if st.button("💬 Chat", key="qa_chat", use_container_width=True):
            fun_go("chat")

    # ── Recent transactions ────────────────────────────────────────────────
    fun_section("Recent Transactions")
    txs = data.get("recent_transactions", [])

    if not txs:
        st.markdown(
            "<p style='color:#888;font-style:italic'>"
            "No transactions yet — make your first deposit!</p>",
            unsafe_allow_html=True,
        )
        return

    rows = []
    for tx in txs:
        sign = "+" if tx["type"] == "CREDIT" else "−"
        rows.append(
            {
                "Date": tx["created_at"].strftime("%d %b %Y"),
                "Type": tx["type"],
                f"Amount ({sign})": fun_fmt_inr(tx["amount"]),
                "Category": tx.get("category") or "—",
                "Note": tx.get("note") or "—",
                "Balance After": fun_fmt_inr(tx["balance_after"]),
            }
        )
    df = pd.DataFrame(rows)

    def _style_type(val: str) -> str:
        """Return a CSS background style for CREDIT/DEBIT cells."""
        if val == "CREDIT":
            return "background-color:#E8F5E9; color:#1B5E20; font-weight:700"
        if val == "DEBIT":
            return "background-color:#FCE4EC; color:#880E4F; font-weight:700"
        return ""

    styled = df.style.map(_style_type, subset=["Type"])
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ===========================================================================
# Deposit
# ===========================================================================


def fun_show_deposit() -> None:
    """Render the deposit form.

    Returns:
        None
    """
    fun_page_title("Deposit Funds")

    if not fun_ensure_account():
        st.error("No bank account found. Please contact support.")
        return

    acct = fun_get_account(st.session_state.user_id)
    if acct:
        fun_card(
            "Available Balance",
            fun_fmt_inr(acct["balance"]),
            variant="green",
        )

    _, form_col, _ = st.columns([1, 2, 1])
    with form_col:
        with st.form("deposit_form"):
            amount_str = st.text_input(
                "Amount (INR)", placeholder="e.g. 1000.00"
            )
            category = st.selectbox(
                "Category (optional)",
                ["", "Salary", "Freelance", "Transfer", "Gift", "Refund", "Other"],
            )
            note = st.text_input(
                "Note (optional)", placeholder="e.g. Monthly salary"
            )
            submitted = st.form_submit_button(
                "Deposit", use_container_width=True
            )

    if submitted:
        try:
            amount = (
                Decimal(amount_str.strip()) if amount_str.strip() else Decimal("0")
            )
        except Exception:
            st.error("Please enter a valid numeric amount.")
            return

        result = fun_deposit(
            st.session_state.account_id,
            amount,
            category or None,
            note.strip() or None,
        )
        if result["ok"]:
            st.success(
                f"Deposited {fun_fmt_inr(amount)} successfully! "
                f"New balance: **{fun_fmt_inr(result['balance'])}**"
            )
            st.balloons()
        else:
            st.error(result["error"])


# ===========================================================================
# Withdraw
# ===========================================================================


def fun_show_withdraw() -> None:
    """Render the withdrawal form.

    Returns:
        None
    """
    fun_page_title("Withdraw Funds")

    if not fun_ensure_account():
        st.error("No bank account found. Please contact support.")
        return

    acct = fun_get_account(st.session_state.user_id)
    if acct:
        fun_card(
            "Available Balance",
            fun_fmt_inr(acct["balance"]),
            sub="Maximum withdrawal amount",
            variant="green",
        )

    _, form_col, _ = st.columns([1, 2, 1])
    with form_col:
        with st.form("withdraw_form"):
            amount_str = st.text_input(
                "Amount (INR)", placeholder="e.g. 500.00"
            )
            category = st.selectbox(
                "Category (optional)",
                [
                    "",
                    "Food",
                    "Transport",
                    "Shopping",
                    "Bills",
                    "Entertainment",
                    "ATM",
                    "Other",
                ],
            )
            note = st.text_input(
                "Note (optional)", placeholder="e.g. Grocery run"
            )
            submitted = st.form_submit_button(
                "Withdraw", use_container_width=True
            )

    if submitted:
        try:
            amount = (
                Decimal(amount_str.strip()) if amount_str.strip() else Decimal("0")
            )
        except Exception:
            st.error("Please enter a valid numeric amount.")
            return

        result = fun_withdraw(
            st.session_state.account_id,
            amount,
            category or None,
            note.strip() or None,
        )
        if result["ok"]:
            st.success(
                f"Withdrawn {fun_fmt_inr(amount)} successfully! "
                f"New balance: **{fun_fmt_inr(result['balance'])}**"
            )
        else:
            st.error(result["error"])


# ===========================================================================
# Statement
# ===========================================================================


def fun_show_statement() -> None:
    """Render the filterable bank statement with CSV download.

    Returns:
        None
    """
    fun_page_title("Bank Statement")

    if not fun_ensure_account():
        st.error("No bank account found.")
        return

    # ── Filters ───────────────────────────────────────────────────────────
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        from_date = st.date_input("From date", value=None, key="stmt_from")
    with fc2:
        to_date = st.date_input("To date", value=None, key="stmt_to")
    with fc3:
        type_choice = st.selectbox("Type", ["All", "CREDIT", "DEBIT"])

    result = fun_get_statement(
        st.session_state.account_id,
        from_date=from_date if from_date else None,
        to_date=to_date if to_date else None,
        tx_type=None if type_choice == "All" else type_choice,
    )

    if not result["ok"]:
        st.error(result["error"])
        return

    rows = result["rows"]

    if not rows:
        st.info("No transactions match the selected filters.")
        return

    fun_section(f"{len(rows)} Transaction(s)")

    table_rows = []
    for r in rows:
        sign = "+" if r["type"] == "CREDIT" else "−"
        table_rows.append(
            {
                "Date & Time": r["created_at"].strftime("%d %b %Y %H:%M"),
                "Type": r["type"],
                "Amount": f"{sign} {fun_fmt_inr(r['amount'])}",
                "Category": r.get("category") or "—",
                "Note": r.get("note") or "—",
                "Balance After": fun_fmt_inr(r["balance_after"]),
            }
        )
    df = pd.DataFrame(table_rows)

    def _style_type(val: str) -> str:
        """Return CSS for CREDIT/DEBIT cells in the statement table."""
        if val == "CREDIT":
            return "background-color:#E8F5E9; color:#1B5E20; font-weight:700"
        if val == "DEBIT":
            return "background-color:#FCE4EC; color:#880E4F; font-weight:700"
        return ""

    styled = df.style.map(_style_type, subset=["Type"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    csv_bytes = fun_generate_csv(rows).encode("utf-8")
    st.download_button(
        label="⬇ Download as CSV",
        data=csv_bytes,
        file_name="aarambh_statement.csv",
        mime="text/csv",
        use_container_width=False,
    )


# ===========================================================================
# Chat
# ===========================================================================


def fun_show_chat() -> None:
    """Render the WhatsApp-style GenAI chat assistant.

    Returns:
        None
    """
    fun_page_title("Chat Assistant")
    st.markdown(
        "<p style='color:#555;margin-top:-1rem;margin-bottom:1rem'>"
        "Ask me about your balance, spending by category, recent activity, "
        "or anything else about your account.</p>",
        unsafe_allow_html=True,
    )

    if not fun_ensure_account():
        st.error("No bank account found.")
        return

    # Initialise ChatSession once per login
    if st.session_state.chat_session is None:
        try:
            st.session_state.chat_session = fun_create_session(
                account_id=st.session_state.account_id,
                username=st.session_state.username,
            )
        except EnvironmentError as exc:
            st.error(str(exc))
            return

    # Clear chat button (top-right)
    _, btn_col = st.columns([5, 1])
    with btn_col:
        if st.button("Clear chat", key="clear_chat", use_container_width=True):
            st.session_state.chat_session.fun_clear()
            st.session_state.chat_messages = []
            st.rerun()

    # ── Build chat HTML ────────────────────────────────────────────────────
    parts = []
    for msg in st.session_state.chat_messages:
        safe = html.escape(msg["content"]).replace("\n", "<br>")
        if msg["role"] == "user":
            parts.append(
                f'<div class="ab-chat-row-user">'
                f'<div class="ab-bubble-user">{safe}</div>'
                f"</div>"
            )
        else:
            parts.append(
                f'<div class="ab-chat-row-assistant">'
                f'<div class="ab-bubble-assistant">{safe}</div>'
                f"</div>"
            )

    empty_msg = (
        "<p style='text-align:center;color:#AAA;padding-top:170px'>"
        "Start the conversation below ✨</p>"
    )
    chat_html = "".join(parts) if parts else empty_msg

    st.markdown(
        f'<div class="ab-chat-box">{chat_html}</div>',
        unsafe_allow_html=True,
    )

    # ── Input ──────────────────────────────────────────────────────────────
    with st.form("chat_form", clear_on_submit=True):
        inp_col, send_col = st.columns([6, 1])
        with inp_col:
            user_input = st.text_input(
                "Message",
                placeholder="e.g. What did I spend on food last month?",
                label_visibility="collapsed",
            )
        with send_col:
            send = st.form_submit_button("Send", use_container_width=True)

    if send and user_input.strip():
        msg_text = user_input.strip()
        st.session_state.chat_messages.append(
            {"role": "user", "content": msg_text}
        )
        with st.spinner("Thinking..."):
            try:
                reply = st.session_state.chat_session.fun_chat(msg_text)
            except Exception:
                reply = (
                    "Sorry, I encountered an error. "
                    "Please check your API key and try again."
                )
        st.session_state.chat_messages.append(
            {"role": "assistant", "content": reply}
        )
        st.rerun()


# ===========================================================================
# Router / main
# ===========================================================================


def main() -> None:
    """Initialise the app and route to the current page.

    Returns:
        None
    """
    fun_inject_css()
    fun_init_session()

    # Unauthenticated: only login and register pages
    if not st.session_state.logged_in:
        if st.session_state.page == "register":
            fun_show_register()
        else:
            fun_show_login()
        return

    # Authenticated: sidebar + page router
    fun_show_sidebar()

    page_map = {
        "dashboard": fun_show_dashboard,
        "deposit":   fun_show_deposit,
        "withdraw":  fun_show_withdraw,
        "statement": fun_show_statement,
        "chat":      fun_show_chat,
    }
    page_map.get(st.session_state.page, fun_show_dashboard)()


main()
