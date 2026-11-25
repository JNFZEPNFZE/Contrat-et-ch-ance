"use strict";

const $ = (s) => document.querySelector(s);
let contrats = [];        // tous les contrats (tous immeubles confondus)
let immeubles = [];
let dossier = "";         // "" = tous, "aucun" = sans immeuble, sinon id d'immeuble (chaîne)
let enEdition = null;
let immeubleEnEdition = null;

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
  [contrats, immeubles] = await Promise.all([api("GET", "/api/contrats"), api("GET", "/api/immeubles")]);
  if (dossier && dossier !== "aucun" && !immeubles.some((i) => String(i.id) === dossier)) dossier = "";
  majCategories();
  afficher();
}

const dansDossier = (c) =>
  !dossier || (dossier === "aucun" ? c.immeuble_id == null : String(c.immeuble_id) === dossier);

function majCategories() {
  const cats = [...new Set(contrats.map((c) => c.categorie).filter(Boolean))].sort();
  const sel = $("#filtre-categorie");
  const courant = sel.value;
  sel.innerHTML = '<option value="">Toutes les catégories</option>' +
    cats.map((c) => `<option>${echap(c)}</option>`).join("");
  sel.value = cats.includes(courant) ? courant : "";
  $("#categories").innerHTML = cats.map((c) => `<option value="${echap(c)}">`).join("");
}

// ------------------------------------------------------------------ Dossiers
function afficherDossiers() {
  const urg = (liste) => liste.filter((c) => c.statut === "urgent").length;
  const sansImmeuble = contrats.filter((c) => c.immeuble_id == null);
  const entree = (cle, nom, nb, nbUrgents, sous = "") => `
    <li><button class="dossier ${cle === dossier ? "actif" : ""}" data-dossier="${cle}">
      <span class="icone" aria-hidden="true">${cle && cle !== "aucun" ? "🏢" : "📁"}</span>
      <span class="nom-d">${echap(nom)}${sous ? `<span class="sous">${echap(sous)}</span>` : ""}</span>
      ${nbUrgents ? `<span class="badge urgent" title="${nbUrgents} action(s) urgente(s)">${nbUrgents}</span>` : ""}
      <span class="badge">${nb}</span>
    </button></li>`;

  let html = entree("", "Tous les immeubles", contrats.length, urg(contrats));
  html += immeubles.map((i) => entree(String(i.id), i.nom, i.nb_contrats, i.nb_urgents, i.adresse)).join("");
  if (sansImmeuble.length) html += entree("aucun", "Sans immeuble", sansImmeuble.length, urg(sansImmeuble));
  if (!immeubles.length) html += '<li class="aide">Créez un immeuble pour y classer ses contrats.</li>';
  $("#liste-dossiers").innerHTML = html;

  const imm = immeubles.find((i) => String(i.id) === dossier);
  $("#nom-dossier").textContent = imm ? imm.nom : dossier === "aucun" ? "Sans immeuble" : "Tous les immeubles";
  $("#adresse-dossier").textContent = imm?.adresse || "";
  $("#btn-modifier-immeuble").hidden = !imm;
  document.body.classList.toggle("vue-globale", !dossier);

  const q = dossier ? `?immeuble=${dossier}` : "";
  $("#lien-csv").href = `/api/export.csv${q}`;
  $("#lien-ics").href = `/api/export.ics${q}`;
}

// ------------------------------------------------------------------ Contrats
function afficherTuiles(liste) {
  const compte = (s) => liste.filter((c) => c.statut === s).length;
  const actifs = liste.filter((c) => !["expire", "resilie"].includes(c.statut));
  const annuel = actifs.reduce((t, c) => {
    const f = { Mensuel: 12, Trimestriel: 4, Semestriel: 2, Annuel: 1 }[c.periodicite];
    return t + (f && c.montant ? c.montant * f : 0);
  }, 0);
  const tuiles = [
    ["", "Contrats actifs", actifs.length],
    ["urgent", "Action urgente", compte("urgent")],
    ["a_surveiller", "À surveiller", compte("a_surveiller")],
    ["expire", "Expirés", compte("expire")],
    ["", "Coût annuel estimé", fmtMontant(annuel)],
  ];
  const filtre = $("#filtre-statut").value;
  $("#tuiles").innerHTML = tuiles
    .map(([s, l, v]) =>
      `<div class="tuile ${s} ${s && s === filtre ? "actif" : ""}" data-statut="${s}">
         <div class="valeur">${v}</div><div class="libelle">${l}</div></div>`)
    .join("");
}

function afficher() {
  afficherDossiers();
  const duDossier = contrats.filter(dansDossier);
  afficherTuiles(duDossier);

  const q = $("#recherche").value.trim().toLowerCase();
  const st = $("#filtre-statut").value;
  const cat = $("#filtre-categorie").value;
  const liste = duDossier.filter((c) =>
    (!st || c.statut === st) &&
    (!cat || c.categorie === cat) &&
    (!q || [c.nom, c.partenaire, c.reference, c.responsable, c.categorie, c.notes, c.immeuble_nom]
      .some((v) => (v || "").toLowerCase().includes(q))));

  const vide = $("#vide");
  vide.hidden = liste.length > 0;
  vide.textContent = duDossier.length
    ? "Aucun contrat ne correspond aux filtres."
    : "Aucun contrat dans ce dossier. Cliquez sur « + Nouveau contrat » pour en ajouter un.";

  $("#liste").innerHTML = liste.map((c) => `
    <tr data-id="${c.id}">
      <td><span class="pastille ${c.statut}">${echap(c.statut_libelle)}</span></td>
      <td><strong>${echap(c.nom)}</strong><span class="sous">${echap([c.reference, c.categorie].filter(Boolean).join(" · "))}</span></td>
      <td class="col-immeuble">${echap(c.immeuble_nom) || '<span class="sous">—</span>'}</td>
      <td>${echap(c.partenaire)}<span class="sous">${echap(c.responsable)}</span></td>
      <td>${fmtDate(c.date_action)}<span class="sous">${delai(c.jours_restants)}</span></td>
      <td>${fmtDate(c.limite_resiliation)}${c.preavis_depasse ? `<span class="sous alerte-preavis">${c.reconduction_tacite ? "trop tard pour l'échéance précédente : reconduit" : "préavis dépassé"}</span>` : ""}</td>
      <td>${fmtDate(c.echeance)}</td>
      <td>${c.reconduction_tacite ? `Tacite · ${c.duree_reconduction_mois} mois` : "Non"}</td>
      <td class="num">${fmtMontant(c.montant)}<span class="sous">${echap(c.periodicite)}</span></td>
      <td><button class="bouton secondaire petit" data-modifier="${c.id}">Modifier</button></td>
    </tr>`).join("");
}

// ---------------------------------------------------------- Formulaire contrat
function remplirSelectImmeubles() {
  $("#select-immeuble").innerHTML = '<option value="">— Sans immeuble —</option>' +
    immeubles.map((i) => `<option value="${i.id}">${echap(i.nom)}</option>`).join("");
}

function ouvrir(c) {
  enEdition = c ? c.id : null;
  const f = $("#formulaire");
  f.reset();
  remplirSelectImmeubles();
  $("#titre-form").textContent = c ? "Modifier le contrat" : "Nouveau contrat";
  $("#btn-supprimer").hidden = !c;
  $("#erreur").hidden = true;
  if (c) {
    for (const el of f.elements) {
      if (!el.name || !(el.name in c)) continue;
      if (el.type === "checkbox") el.checked = !!c[el.name];
      else el.value = c[el.name] ?? "";
    }
  } else {
    // Nouveau contrat : rangé par défaut dans le dossier ouvert.
    f.immeuble_id.value = dossier && dossier !== "aucun" ? dossier : "";
  }
  $("#dialogue").showModal();
  f.nom.focus();
}

function lireFormulaire(f) {
  const d = {};
  for (const el of f.elements) {
    if (!el.name) continue;
    d[el.name] = el.type === "checkbox" ? el.checked : el.value;
  }
  return d;
}

function surErreur(sel, err) {
  $(sel).textContent = err.message;
  $(sel).hidden = false;
}

$("#formulaire").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const d = lireFormulaire(e.target);
    if (enEdition) await api("PUT", `/api/contrats/${enEdition}`, d);
    else await api("POST", "/api/contrats", d);
    $("#dialogue").close();
    await charger();
  } catch (err) { surErreur("#erreur", err); }
});

$("#btn-supprimer").addEventListener("click", async () => {
  if (!enEdition || !confirm("Supprimer définitivement ce contrat ?")) return;
  await api("DELETE", `/api/contrats/${enEdition}`);
  $("#dialogue").close();
  await charger();
});

// --------------------------------------------------------- Formulaire immeuble
function ouvrirImmeuble(i) {
  immeubleEnEdition = i ? i.id : null;
  const f = $("#formulaire-immeuble");
  f.reset();
  $("#titre-form-immeuble").textContent = i ? "Modifier l'immeuble" : "Nouvel immeuble";
  $("#btn-supprimer-immeuble").hidden = !i;
  $("#erreur-immeuble").hidden = true;
  if (i) for (const n of ["nom", "adresse", "notes"]) f[n].value = i[n] ?? "";
  $("#dialogue-immeuble").showModal();
  f.nom.focus();
}

$("#formulaire-immeuble").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const d = lireFormulaire(e.target);
    const res = immeubleEnEdition
      ? await api("PUT", `/api/immeubles/${immeubleEnEdition}`, d)
      : await api("POST", "/api/immeubles", d);
    $("#dialogue-immeuble").close();
    dossier = String(res.id);  // ouvre le dossier créé / modifié
    await charger();
  } catch (err) { surErreur("#erreur-immeuble", err); }
});

$("#btn-supprimer-immeuble").addEventListener("click", async () => {
  if (!immeubleEnEdition || !confirm("Supprimer cet immeuble ?")) return;
  try {
    await api("DELETE", `/api/immeubles/${immeubleEnEdition}`);
    $("#dialogue-immeuble").close();
    dossier = "";
    await charger();
  } catch (err) { surErreur("#erreur-immeuble", err); }
});

// ------------------------------------------------------------------ Événements
document.querySelectorAll("[data-fermer]").forEach((b) =>
  b.addEventListener("click", () => b.closest("dialog").close()));
$("#btn-nouveau").addEventListener("click", () => ouvrir(null));
$("#btn-nouvel-immeuble").addEventListener("click", () => ouvrirImmeuble(null));
$("#btn-modifier-immeuble").addEventListener("click", () =>
  ouvrirImmeuble(immeubles.find((i) => String(i.id) === dossier)));
$("#liste-dossiers").addEventListener("click", (e) => {
  const b = e.target.closest("[data-dossier]");
  if (!b) return;
  dossier = b.dataset.dossier;
  afficher();
});
$("#liste").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-id]");
  if (tr) ouvrir(contrats.find((c) => c.id === Number(tr.dataset.id)));
});
$("#tuiles").addEventListener("click", (e) => {
  const t = e.target.closest(".tuile");
  if (!t) return;
  const s = t.dataset.statut;
  $("#filtre-statut").value = $("#filtre-statut").value === s ? "" : s;
  afficher();
});
["#recherche", "#filtre-statut", "#filtre-categorie"].forEach((s) =>
  $(s).addEventListener("input", afficher));

charger();
