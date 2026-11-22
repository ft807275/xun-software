const back = document.getElementById("login-back");
const from = document.referrer ? new URL(document.referrer) : null;
if (history.state?.appBack || (history.length > 1 && from?.origin === location.origin && from.pathname === "/")) {
  back.disabled = false;
  back.title = "返回上一页";
  back.addEventListener("click", () => history.back());
}
fetch("/api/auth")
  .then((r) => r.json())
  .then((a) => {
    for (const id of ["act", "confirm"])
      document.getElementById(id).hidden = !a.setup;
  });
document.getElementById("login").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const r = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(new FormData(e.target))),
    });
    const v = await r.json();
    if (!r.ok) throw Error(v.error);
    location.replace("/");
  } catch (err) {
    document.getElementById("error").textContent = err.message;
  }
};
