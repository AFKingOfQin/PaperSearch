import os
from string import punctuation
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


@st.fragment
def project_menu(projects, project):
    escaped = str.maketrans({char: "\\" + char for char in punctuation})
    st.markdown("Project")
    with st.popover(
        projects[project]["topic"].translate(escaped),
        key=f"project-menu-{project}",
        width="stretch",
    ):
        query = st.text_input(
            "Search projects",
            placeholder="Search projects",
            label_visibility="collapsed",
            live=True,
        ).casefold()
        for project_id, item in projects.items():
            topic = item["topic"]
            if query not in topic.casefold():
                continue
            option, action = st.columns([4, 1], gap=None, wrap=False)
            if option.button(
                topic.translate(escaped),
                key=f"select-{project_id}",
                type="tertiary",
                wrap=True,
            ):
                st.session_state.project_id = project_id
                st.rerun()
            if action.button(
                "Delete",
                key=f"delete-{project_id}",
                type="tertiary",
                help=f"Delete project {topic.translate(escaped)}",
            ):
                call("DELETE", f"/projects/{project_id}")
                if project_id == project:
                    st.session_state.pop("project_id", None)
                st.rerun()


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
        project = st.session_state.get("project_id")
        if project not in projects:
            project = next(iter(projects))
            st.session_state.project_id = project
        project_menu(projects, project)
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
    f"{status['metadata']:,} current papers · {coverage['lexical']:,} lexical · {coverage['semantic']:,} semantic vectors"
)
if "semantic_eligible" in coverage:
    st.caption(
        f"Semantic index covers {coverage['semantic']:,} of {coverage['semantic_eligible']:,} eligible papers."
    )
if dates := active.get("semantic_submission_dates"):
    st.caption(f"Semantic vectors span submissions from {dates[0]} to {dates[1]}.")
if scope := active.get("semantic_scope"):
    with st.expander("Semantic date and subject coverage"):
        for group, label in (("recent", "Recent CS/ML"), ("other", "Historical sample")):
            if dates := scope.get(f"{group}_dates"):
                st.caption(f"{label} submissions span {dates[0]} to {dates[1]}.")
        for cohort in scope.get("cohorts", []):
            subjects = " + ".join(cohort["categories"])
            period = f"from {cohort['start']}"
            if cohort["before"]:
                period += f" to before {cohort['before']}"
            st.caption(
                f"{subjects} {period} · {cohort['indexed']:,} of {cohort['eligible']:,} indexed"
            )
        if years := scope.get("recent_years"):
            st.write("Recent vectors by submission year", years)
        if categories := scope.get("recent_categories"):
            st.write("Recent vectors by category (includes cross-listings)", categories)
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
offset, snapshot, *previous_ranker = st.session_state.get("page", (0, None))
page = call(
    "GET",
    prefix + "/search",
    params=dict(
        q=query, ranker=ranker, field=field, offset=offset, limit=10, snapshot=snapshot
    ),
)
served = page["ranker"]
if offset and previous_ranker and served != previous_ranker[0]:
    st.session_state.page = (0, page["snapshot_id"], served)
    st.rerun()
if reason := page.get("fallback_reason"):
    st.warning(f"{reason}. Showing BM25 results.")
if page["query_truncated"]:
    st.caption("The semantic query was shortened to 128 tokens.")
hits = {row["revision_id"]: row for row in page["results"]}
if not hits:
    st.info("No matches.")
    st.stop()
previous, following = st.columns(2)
if previous.button("Previous page", disabled=offset == 0):
    st.session_state.page = (offset - 10, page["snapshot_id"], served)
    st.rerun()
if following.button("Next page", disabled=not page["has_more"]):
    st.session_state.page = (offset + 10, page["snapshot_id"], served)
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
