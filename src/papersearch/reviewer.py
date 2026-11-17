import os
from uuid import uuid4

import requests
import streamlit as st

BASE = os.environ.get("PAPERSEARCH_API", "http://127.0.0.1:18080")
st.set_page_config(page_title="PaperSearch", layout="wide")
st.title("PaperSearch")


def call(method, path, **kwargs):
    try:
        result = requests.request(method, BASE + path, timeout=(4, 90), **kwargs)
    except requests.RequestException as exc:
        st.error(str(exc))
        st.stop()
    if not result.ok:
        st.error(
            result.json()["detail"]
            if result.headers.get("content-type", "").startswith("application/json")
            else result.text
        )
        if (
            result.status_code == 409
            and "/search" in path
            and st.button("Restart search")
        ):
            st.session_state.pop("page", None)
            st.rerun()
        st.stop()
    return result.json()


with st.sidebar:
    with st.form("project"):
        topic = st.text_input("New project topic")
        criteria = st.text_area("Screening criteria")
        if st.form_submit_button("Create project"):
            created = call(
                "POST", "/projects", json=dict(topic=topic, criteria=criteria)
            )
            st.session_state.project_id = created["project_id"]
            st.rerun()
    projects = {p["project_id"]: p for p in call("GET", "/projects")}
    if projects:
        project = st.selectbox(
            "Project",
            list(projects),
            format_func=lambda p: projects[p]["topic"],
            key="project_id",
        )
        if projects[project]["criteria"]:
            st.write(projects[project]["criteria"])
        public = os.environ.get("PAPERSEARCH_PUBLIC_API", BASE)
        st.link_button(
            "Export decisions (CSV)", f"{public}/projects/{project}/export.csv"
        )

status = call("GET", "/status")
active = status["active"]
if active is None:
    st.info("Publish a search snapshot to begin screening.")
    st.stop()
coverage = active["coverage"]
st.caption(
    f"{status['metadata']:,} current papers · {coverage['lexical']:,} lexical · {coverage['semantic']:,} semantic"
)
if "semantic_eligible" in coverage:
    st.caption(
        f"Semantic index covers {coverage['semantic']:,} of {coverage['semantic_eligible']:,} eligible papers."
    )
if status["generation"] != active["generation"]:
    st.warning("New metadata is available. Search shows the published revisions.")
if not projects:
    st.info("Create a review project to begin.")
    st.stop()

prefix = f"/projects/{project}"
query = st.text_input("Search papers")
ranker = st.selectbox("Ranking", ["bm25", "semantic"])
field = (
    st.selectbox("Search in", ["all", "title", "abstract"])
    if ranker == "bm25"
    else "all"
)
if not query.strip():
    st.stop()
search_key = (project, query, ranker, field)
if st.session_state.get("search_key") != search_key:
    st.session_state.search_key = search_key
    st.session_state.pop("page", None)
offset, snapshot = st.session_state.get("page", (0, None))
page = call(
    "GET",
    prefix + "/search",
    params=dict(
        q=query, ranker=ranker, field=field, offset=offset, limit=10, snapshot=snapshot
    ),
)
if page["query_truncated"]:
    st.caption("The semantic query was shortened to 128 tokens.")
hits = {row["revision_id"]: row for row in page["results"]}
if not hits:
    st.info("No matches.")
    st.stop()
previous, following = st.columns(2)
if previous.button("Previous page", disabled=offset == 0):
    st.session_state.page = (offset - 10, page["snapshot_id"])
    st.rerun()
if following.button("Next page", disabled=not page["has_more"]):
    st.session_state.page = (offset + 10, page["snapshot_id"])
    st.rerun()

chosen = st.radio(
    "Search results",
    list(hits),
    format_func=lambda r: f"{hits[r]['rank']}. {hits[r]['title']}",
)
paper = hits[chosen]["paper_id"]
detail = call("GET", "/papers/detail", params=dict(paper=paper, revision_id=chosen))
revisions = {item["revision_id"]: item for item in detail["revisions"]}
selected = st.selectbox(
    "Inspect revision",
    list(revisions),
    index=list(revisions).index(chosen),
    format_func=lambda r: (
        f"v{revisions[r]['version_rank']} · {revisions[r]['source_updated_at']} · #{r}"
    ),
    key=f"revision-{chosen}",
)
if selected != chosen:
    detail = call(
        "GET", "/papers/detail", params=dict(paper=paper, revision_id=selected)
    )
payload = detail["payload"]
st.subheader(payload["title"])
st.caption(", ".join(payload["categories"]))
st.write(payload["abstract"])
st.link_button("Open source", payload["source_url"])
if detail["current_revision_id"] != selected:
    st.warning("You are viewing a superseded revision.")

review = call("GET", prefix + "/decision", params={"paper": paper})
current = review["current"] or {}
if current.get("needs_reconsideration"):
    st.warning("The reviewed text has changed. Reconsider this decision.")
labels = ["relevant", "irrelevant", "uncertain"]
with st.form(f"decision-{project}-{selected}-{current.get('history_id')}"):
    label = st.selectbox(
        "Label", labels, index=labels.index(current.get("label", "uncertain"))
    )
    note = st.text_area("Review note", current.get("note", ""))
    if st.form_submit_button("Save decision"):
        identity = (project, paper, selected, label, note)
        if st.session_state.get("submission") != identity:
            st.session_state.submission = identity
            st.session_state.request_id = str(uuid4())
        call(
            "PUT",
            prefix + "/decision",
            params={"paper": paper},
            json=dict(
                revision_id=selected,
                label=label,
                note=note,
                request_id=st.session_state.request_id,
            ),
        )
        del st.session_state.submission
        st.rerun()
if review["history"]:
    with st.expander("Decision history"):
        st.table(review["history"])
