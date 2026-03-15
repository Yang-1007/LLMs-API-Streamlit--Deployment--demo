import streamlit as st
from config import *
import agents

from tools import create_local_database, CSV_PATH, DB_PATH
from agents import run_single_agent, run_multi_agent



MODEL_SMALL  = "gpt-4o-mini"
MODEL_LARGE  = "gpt-4o"
agents.ACTIVE_MODEL = MODEL_SMALL

if not os.path.exists(DB_PATH):
    create_local_database(CSV_PATH)

st.set_page_config(page_title="Stock Agent Chat", page_icon="📈", layout="wide")
st.title("📈Stock Agent Chat")

# -----------------------------
# Sidebar
# -----------------------------
with st.sidebar:
    st.header("Controls")

    agent_mode = st.selectbox(
        "Agent selector",
        ["Single Agent", "Multi-Agent"],
        index=0
    )

    model_name = st.selectbox(
        "Model selector",
        ["gpt-4o-mini", "gpt-4o"],
        index=0
    )

    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.turn_history = []
        st.rerun()

# -----------------------------
# Session state
# -----------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

# turn_history is passed to the agents
# format: [{"role": "user"/"assistant", "content": "..."}]
if "turn_history" not in st.session_state:
    st.session_state.turn_history = []

# -----------------------------
# Set active model
# -----------------------------
ACTIVE_MODEL = model_name

# -----------------------------
# Display conversation history
# -----------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            meta = []
            if "architecture" in msg:
                meta.append(f"**Architecture:** {msg['architecture']}")
            if "model" in msg:
                meta.append(f"**Model:** {msg['model']}")
            if meta:
                st.caption(" | ".join(meta))

# -----------------------------
# Chat input
# -----------------------------
user_input = st.chat_input("Ask a stock question...")

if user_input:
    # Show user message
    st.session_state.messages.append({"role": "user", "content": user_input})
    st.session_state.turn_history.append({"role": "user", "content": user_input})

    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                if agent_mode == "Single Agent":
                    result = run_single_agent(
                        question=user_input,
                        conversation_history=st.session_state.turn_history[:-1],  # prior turns only
                        verbose=False
                    )
                    final_answer = result.answer
                    architecture_used = "single-agent"

                else:
                    result = run_multi_agent(
                        question=user_input,
                        conversation_history=st.session_state.turn_history[:-1],  # prior turns only
                        verbose=False
                    )
                    final_answer = result["final_answer"]
                    architecture_used = result["architecture"]

                st.markdown(final_answer)
                st.caption(f"**Architecture:** {architecture_used} | **Model:** {model_name}")

            except Exception as e:
                final_answer = f"Error: {str(e)}"
                architecture_used = agent_mode.lower().replace(" ", "-")
                st.error(final_answer)

    # Save assistant message
    st.session_state.messages.append({
        "role": "assistant",
        "content": final_answer,
        "architecture": architecture_used,
        "model": model_name,
    })
    st.session_state.turn_history.append({"role": "assistant", "content": final_answer})