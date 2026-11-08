"""Sign in / account. Field evidence (field maps, assessments, visits, photos, exact locations) is shown only to
the account that owns those pilot areas. Accounts are stored as password hashes in the app's secrets."""
import time
import streamlit as st
from _lib import (html_block, icon, footer, page_title, auth_users, current_user, user_pilots, _cfg, link, E)
from fieldpriority.auth import authenticate

user = current_user()
if user:
    page_title("Your account", f"Signed in as {user['name']}.", eyebrow="FieldPriority", icon_name="lock")
    ps = user_pilots()
    html_block('<div class="fp-panel-h"><span>Your pilot areas</span></div><div style="display:flex;gap:8px;'
               'flex-wrap:wrap;margin-bottom:.8rem">' + "".join(
                   f'<a class="fp-btn ghost" style="color:var(--forest);border-color:var(--forest)" '
                   f'href="{link("/assessments", area=p)}" target="_self">{icon("field", 16)} {E(_cfg(p)["pilot_short"])}</a>'
                   for p in ps) + '</div>' if ps else
               '<p>No pilot areas are linked to this account yet.</p>')
    st.caption("Field maps, assessments, visits and photos for these areas are visible only while you are signed in. "
               "Refreshing the browser signs you out.")
    if st.button("Sign out", icon=":material/logout:"):
        for k in ("fp_user", "pilot", "_area_seen"):
            st.session_state.pop(k, None)
        st.rerun()
else:
    page_title("Sign in", "Field evidence is protected: each account sees only its own fields.",
               eyebrow="FieldPriority", icon_name="lock")
    users = auth_users()
    left, _ = st.columns([1.1, 1.4])
    with left:
        if not users:
            st.warning("No accounts are set up for this app yet. On the project computer run **set_password.bat**, "
                       "then add the account block to the app's Secrets.")
        wait = st.session_state.get("_login_lock", 0) - time.time()
        with st.form("login", border=True):
            u = st.text_input("Username", autocomplete="username")
            p = st.text_input("Password", type="password", autocomplete="current-password")
            go = st.form_submit_button("Sign in", type="primary", width="stretch", disabled=not users)
        if go:
            if wait > 0:
                st.error(f"Too many attempts. Try again in {int(wait) + 1} seconds.")
            else:
                acc = authenticate(users, u, p)
                if acc:
                    st.session_state["fp_user"] = {"username": u.strip().lower(), "name": acc["name"],
                                                   "pilots": acc["pilots"]}
                    st.session_state.pop("_login_fails", None)
                    st.session_state.pop("pilot", None)
                    st.rerun()
                n = st.session_state.get("_login_fails", 0) + 1
                st.session_state["_login_fails"] = n
                if n >= 5:
                    st.session_state["_login_lock"] = time.time() + 60
                    st.session_state["_login_fails"] = 0
                st.error("Username or password is not correct.")
    st.caption("District intelligence (Overview, Explore Locations, Zambia Map) stays open to everyone. Field-level "
               "evidence is shared only with the account that collected it.")
html_block(footer())
