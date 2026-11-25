"use strict";

const $ = (s) => document.querySelector(s);
let contrats = [];
let enEdition = null;

const fmtDate = (iso) => (iso ? new Date(iso + "T00:00:00").toLocaleDateString("fr-FR") : "—");
const fmtMontant = (m) =>
  m == null ? "" : m.toLocaleString("fr-FR", { style: "currency", currency: "EUR" });
const echap = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function delai(j) {
  if (j == null) return "";
  if (j === 0) return "aujourd'hui";
  if (j < 0) return `il y a ${-j} j`;
  return `dans ${j} j`;
}

async function api(methode, url, corps) {
  const r = await fetch(url, {
    method: methode,
    headers: corps ? { "Content-Type": "application/json" } : {},
    body: corps ? JSON.stringify(corps) : undefined,
  });
  if (r.status === 204) return null;
  const d = await r.json();
  if (!r.ok) throw new Error(d.erreur || "Erreur");
  return d;
}

async function charger() {
  contrats = await api("GET", "/api/contrats");
  majCategories();
  afficher();
}

function majCategories() {
  const cats = [...new Set(contrats.map((c) => c.categorie).filter(Boolean))].sort();
  const sel = $("#filtre-categorie");
  const courant = sel.value;
  sel.innerHTML = '<option value="">Toutes les catégories</option>' +
    cats.map((c) => `<option>${echap(c)}</option>`).join("");
  sel.value = cats.includes(courant) ? courant : "";
  $("#categories").innerHTML = cats.map((c) => `<option value="${echap(c)}">`).join("");
}

function afficherTuiles() {
  const compte = (s) => contrats.filter((c) => c.statut === s).length;
  const actifs = contrats.filter((c) => !["expire", "resilie"].includes(c.statut));
  const annuel = actifs.reduce((t, c) => {
    const f = { Mensuel: 12, Trimestriel: 4, Semestriel: 2, Annuel: 1 }[c.periodicite];
    return t + (f && c.montant ? c.montant * f : 0);
  }, 0);
  const tuiles = [
    ["", "Contrats actifs", actifs.length],
    ["urgent", "Action urgente", compte("urgent")],
    ["a_surveiller", "À surveiller", compte("a_surveiller")],
    ["expire", "Expirés", compte("expire")],
    [null, "Coût annuel estimé", fmtMontant(annuel)],
  ];
  const filtre = $("#filtre-statut").value;
  $("#tuiles").innerHTML = tuiles
    .map(([s, l, v]) =>
      `<div class="tuile ${s ?? ""} ${s !== null && s === filtre && s ? "actif" : ""}" data-statut="${s ?? ""}">
         <div class="valeur">${v}</div><div class="libelle">${l}</div></div>`)
    .join("");
}

function afficher() {
  afficherTuiles();
  const q = $("#recherche").value.trim().toLowerCase();
  const st = $("#filtre-statut").value;
  const cat = $("#filtre-categorie").value;
  const liste = contrats.filter((c) =>
    (!st || c.statut === st) &&
    (!cat || c.categorie === cat) &&
    (!q || [c.nom, c.partenaire, c.reference, c.responsable, c.categorie, c.notes]
      .some((v) => (v || "").toLowerCase().includes(q))));

  $("#vide").hidden = contrats.length > 0;
  $("#liste").innerHTML = liste.map((c) => `
    <tr data-id="${c.id}">
      <td><span class="pastille ${c.statut}">${echap(c.statut_libelle)}</span></td>
      <td><strong>${echap(c.nom)}</strong><span class="sous">${echap([c.reference, c.categorie].filter(Boolean).join(" · "))}</span></td>
      <td>${echap(c.partenaire)}<span class="sous">${echap(c.responsable)}</span></td>
      <td>${fmtDate(c.date_action)}<span class="sous">${delai(c.jours_restants)}</span></td>
      <td>${fmtDate(c.limite_resiliation)}${c.preavis_depasse ? `<span class="sous alerte-preavis">${c.reconduction_tacite ? "trop tard pour l'échéance précédente : reconduit" : "préavis dépassé"}</span>` : ""}</td>
      <td>${fmtDate(c.echeance)}</td>
      <td>${c.reconduction_tacite ? `Tacite · ${c.duree_reconduction_mois} mois` : "Non"}</td>
      <td class="num">${fmtMontant(c.montant)}<span class="sous">${echap(c.periodicite)}</span></td>
      <td><button class="bouton secondaire" data-modifier="${c.id}">Modifier</button></td>
    </tr>`).join("");
}

function ouvrir(c) {
  enEdition = c ? c.id : null;
  const f = $("#formulaire");
  f.reset();
  $("#titre-form").textContent = c ? "Modifier le contrat" : "Nouveau contrat";
  $("#btn-supprimer").hidden = !c;
  $("#erreur").hidden = true;
  if (c) {
    for (const el of f.elements) {
      if (!el.name || !(el.name in c)) continue;
      if (el.type === "checkbox") el.checked = !!c[el.name];
      else el.value = c[el.name] ?? "";
    }
  }
  $("#dialogue").showModal();
  f.nom.focus();
}

function lireFormulaire() {
  const f = $("#formulaire");
  const d = {};
  for (const el of f.elements) {
    if (!el.name) continue;
    d[el.name] = el.type === "checkbox" ? el.checked : el.value;
  }
  return d;
}

$("#formulaire").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const d = lireFormulaire();
    if (enEdition) await api("PUT", `/api/contrats/${enEdition}`, d);
    else await api("POST", "/api/contrats", d);
    $("#dialogue").close();
    await charger();
  } catch (err) {
    $("#erreur").textContent = err.message;
    $("#erreur").hidden = false;
  }
});

$("#btn-supprimer").addEventListener("click", async () => {
  if (!enEdition || !confirm("Supprimer définitivement ce contrat ?")) return;
  await api("DELETE", `/api/contrats/${enEdition}`);
  $("#dialogue").close();
  await charger();
});

$("#btn-annuler").addEventListener("click", () => $("#dialogue").close());
$("#btn-nouveau").addEventListener("click", () => ouvrir(null));
$("#liste").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-id]");
  if (tr) ouvrir(contrats.find((c) => c.id === Number(tr.dataset.id)));
});
$("#tuiles").addEventListener("click", (e) => {
  const t = e.target.closest(".tuile");
  if (!t || t.dataset.statut === undefined) return;
  const s = t.dataset.statut;
  $("#filtre-statut").value = $("#filtre-statut").value === s ? "" : s;
  afficher();
});
["#recherche", "#filtre-statut", "#filtre-categorie"].forEach((s) =>
  $(s).addEventListener("input", afficher));

charger();
