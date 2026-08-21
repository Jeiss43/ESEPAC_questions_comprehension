import streamlit as st
import os
import agents
import schemas
import exporter
from google import genai
import time
from pydantic import ValidationError

st.set_page_config(page_title="Générateur de Questions (Master)", layout="wide")

# Initialisation de l'état
if "questions" not in st.session_state:
    st.session_state["questions"] = []
if "logs" not in st.session_state:
    st.session_state["logs"] = []
if "echecs" not in st.session_state:
    st.session_state["echecs"] = []
if "tokens_utilises" not in st.session_state:
    st.session_state["tokens_utilises"] = {"in": 0, "out": 0}

def log_message(msg: str):
    st.session_state["logs"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")

# --- Sidebar ---
with st.sidebar:
    if os.path.exists("Logo_Esepac_2021.png"):
        st.image("Logo_Esepac_2021.png", use_container_width=True)
        
    st.header("Configuration")
    
    # Clé API
    default_api_key = os.getenv("GEMINI_API_KEY", "")
    try:
        if not default_api_key and "GEMINI_API_KEY" in st.secrets:
            default_api_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
        
    if default_api_key:
        api_key = default_api_key
        st.success("✅ Clé API détectée et configurée automatiquement.")
    else:
        api_key = st.text_input("Clé API Gemini", value="", type="password", help="Saisissez votre clé API si elle n'est pas configurée dans les paramètres de l'application.")
        
    st.markdown("---")
    st.subheader("Consommation (Tokens)")
    st.metric("Tokens Entrants (Prompt)", st.session_state["tokens_utilises"]["in"])
    st.metric("Tokens Sortants (Gen)", st.session_state["tokens_utilises"]["out"])
    total_tokens = st.session_state["tokens_utilises"]["in"] + st.session_state["tokens_utilises"]["out"]
    st.metric("Total Session", total_tokens)
    
    if st.button("Réinitialiser l'état"):
        st.session_state["questions"] = []
        st.session_state["logs"] = []
        st.session_state["echecs"] = []
        st.session_state["tokens_utilises"] = {"in": 0, "out": 0}
        st.rerun()

# --- Main Area ---
st.title("Génération & Audit Pédagogique (Niveau Compréhension)")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Paramètres")
    uploaded_pdf = st.file_uploader("Document de cours (PDF)", type=["pdf"])
    
    st.markdown("**Ciblage du cours (Optionnel)**")
    contexte_ciblage = st.text_area(
        "Définissez une partie ou un concept spécifique du cours à cibler :",
        placeholder="Exemple : Limiter les questions uniquement au chapitre sur les biais cognitifs..."
    )
    
    st.markdown("**Type de questions souhaité (Choix Exclusif)**")
    type_selection_ui = st.radio("Sélectionnez le type", options=["QCM", "Questions Ouvertes (Essay)"])
    type_code = "qcm" if type_selection_ui == "QCM" else "ouverte"
    
    nb_questions = st.slider("Nombre total de questions", min_value=1, max_value=20, value=5)
    
    btn_generer = st.button("Générer et auditer les questions", type="primary")

with col2:
    st.subheader("Journal d'exécution en direct")
    log_container = st.container(height=300)
    def render_logs():
        log_container.empty()
        with log_container:
            for l in st.session_state["logs"][-15:]:
                st.text(l)
    render_logs()

# --- Logique Principale ---
if btn_generer:
    if not api_key:
        st.error("Veuillez fournir une clé API Gemini.")
        st.stop()
    if not uploaded_pdf:
        st.error("Veuillez téléverser un fichier PDF.")
        st.stop()
        
    client = genai.Client(api_key=api_key)
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    pdf_bytes = uploaded_pdf.read()
    
    log_message("Début du traitement...")
    render_logs()
    
    try:
        with agents.gerer_pdf_gemini(client, pdf_bytes, uploaded_pdf.name) as document_part:
            # 1. Génération
            status_text.text("Étape 1/3 : Génération du lot de questions...")
            progress_bar.progress(20)
            log_message(f"Génération de {nb_questions} questions de type '{type_code}' en cours...")
            render_logs()
            
            raw_questions = agents.generer_lot_questions(client, document_part, nb_questions, type_code, contexte_ciblage)
            
            questions_valides_pydantic = []
            questions_rejetees_init = []
            
            for idx, q_data in enumerate(raw_questions):
                try:
                    if isinstance(q_data, schemas.QuestionModel):
                        q_obj = schemas.QuestionModel(**q_data.model_dump())
                    else:
                        q_obj = schemas.QuestionModel(**q_data)
                    questions_valides_pydantic.append(q_obj)
                except ValidationError as e:
                    log_message(f"Erreur de validation Pydantic (index {idx}). Passée en REJETE.")
                    questions_rejetees_init.append({
                        "id": idx,
                        "data": q_data if isinstance(q_data, dict) else (q_data.model_dump() if hasattr(q_data, 'model_dump') else str(q_data)),
                        "motif": str(e)
                    })
            
            # 2. Audit
            status_text.text("Étape 2/3 : Audit critique du lot...")
            progress_bar.progress(50)
            
            verdicts = []
            if questions_valides_pydantic:
                log_message(f"Audit de {len(questions_valides_pydantic)} questions...")
                render_logs()
                verdicts = agents.auditer_questions(client, document_part, questions_valides_pydantic, contexte_ciblage)
            
            dict_questions = {q.id: q for q in questions_valides_pydantic}
            a_corriger = []
            validees = []
            
            for v in verdicts:
                if v.verdict == "VALIDE" and v.id in dict_questions:
                    validees.append(dict_questions[v.id])
                elif v.verdict == "REJETE" and v.id in dict_questions:
                    a_corriger.append((dict_questions[v.id], v.motif_rejet, v.consigne_correction))
            
            for rej_pyd in questions_rejetees_init:
                try:
                    q_fail = schemas.QuestionModel.model_construct(
                        id=rej_pyd["id"], 
                        type=type_code, 
                        processus_bloom="expliquer", 
                        intitule=f"Question invalide générée (ID: {rej_pyd['id']})", 
                        reponse_attendue="", 
                        explication_pedagogique="Modèle non valide: " + str(rej_pyd["data"]),
                        strategie_pedagogique="N/A"
                    )
                    a_corriger.append((q_fail, rej_pyd["motif"], "Générez un JSON strict respectant le schéma Pydantic pour ce type de question."))
                except Exception as e:
                    pass
                    
            # 3. Correction en lot (optimisation des tokens)
            status_text.text(f"Étape 3/3 : Correction de {len(a_corriger)} questions rejetées...")
            progress_bar.progress(70)
            
            rejets_actuels = a_corriger
            
            for iteration in range(1, 3):
                if not rejets_actuels:
                    break
                    
                log_message(f"Boucle de correction (Itération {iteration}/2) pour {len(rejets_actuels)} questions. Envoi du lot...")
                render_logs()
                
                try:
                    # Corriger tout le lot d'un coup
                    questions_corrigees = agents.corriger_lot_questions(client, document_part, rejets_actuels, contexte_ciblage)
                    
                    if not questions_corrigees:
                        log_message("Aucune question retournée par le processus de correction.")
                        break
                        
                    # Auditer le lot corrigé
                    log_message(f"Audit des {len(questions_corrigees)} questions corrigées...")
                    render_logs()
                    verdicts_correction = agents.auditer_questions(client, document_part, questions_corrigees, contexte_ciblage)
                    
                    dict_corrigees = {q.id: q for q in questions_corrigees}
                    nouveaux_rejets = []
                    
                    for v in verdicts_correction:
                        if v.verdict == "VALIDE" and v.id in dict_corrigees:
                            validees.append(dict_corrigees[v.id])
                            log_message(f"Q{v.id} corrigée et validée !")
                        elif v.verdict == "REJETE" and v.id in dict_corrigees:
                            nouveaux_rejets.append((dict_corrigees[v.id], v.motif_rejet, v.consigne_correction))
                            
                    rejets_actuels = nouveaux_rejets
                    
                except Exception as e:
                    log_message(f"Erreur pendant le lot de correction: {e}")
                    break
                    
            # Les questions toujours dans rejets_actuels après 2 itérations sont définitivement rejetées
            for q_rej, motif, _ in rejets_actuels:
                st.session_state["echecs"].append({
                    "question": q_rej.intitule if hasattr(q_rej, 'intitule') else "Question inconnue",
                    "motif_final": motif
                })
                log_message(f"Question définitivement abandonnée après 2 itérations.")
            
            progress_bar.progress(100)
            status_text.text("Terminé !")
            
            # Stockage
            st.session_state["questions"].extend(validees)
            log_message(f"Bilan : {len(validees)} questions générées et validées avec succès.")
            render_logs()
            
    except Exception as e:
        log_message(f"[Erreur Fatale Pipeline] {str(e)}")
        st.error(f"Une erreur est survenue : {e}")
        render_logs()
        
    st.rerun()

# --- Affichage et Édition ---
st.markdown("---")
st.subheader("Questions Validées (Édition Interactive)")

if not st.session_state["questions"]:
    st.info("Aucune question validée pour le moment.")
else:
    for idx, q in enumerate(st.session_state["questions"]):
        with st.expander(f"{idx+1}. {q.type.upper()} - {q.processus_bloom} : {q.intitule[:50]}...", expanded=False):
            # Stratégie pédagogique (Pour l'enseignant, non exportée)
            st.info(f"**💡 Stratégie Pédagogique (Usage enseignant uniquement) :**\n\n{q.strategie_pedagogique}")
            
            new_intitule = st.text_area("Intitulé de la question", value=q.intitule, key=f"intitule_{idx}")
            st.session_state["questions"][idx].intitule = new_intitule
            
            if q.type == "ouverte":
                new_rep = st.text_area("Réponse attendue", value=q.reponse_attendue, key=f"rep_{idx}")
                st.session_state["questions"][idx].reponse_attendue = new_rep
            elif q.type == "qcm":
                st.markdown("**Options :**")
                for i_opt, opt in enumerate(q.options):
                    new_opt = st.text_input(f"Option {i_opt+1}", value=opt, key=f"opt_{idx}_{i_opt}")
                    st.session_state["questions"][idx].options[i_opt] = new_opt
                
                # S'assurer que la réponse attendue est bien dans la liste pour le selectbox
                rep_idx = 0
                if q.reponse_attendue in st.session_state["questions"][idx].options:
                    rep_idx = st.session_state["questions"][idx].options.index(q.reponse_attendue)
                
                new_rep_qcm = st.selectbox("Réponse correcte", options=st.session_state["questions"][idx].options, index=rep_idx, key=f"rep_qcm_{idx}")
                st.session_state["questions"][idx].reponse_attendue = new_rep_qcm
            
            new_expl = st.text_area("Feedback à l'étudiant (Tutoiement recommandé)", value=q.explication_pedagogique, key=f"expl_{idx}")
            st.session_state["questions"][idx].explication_pedagogique = new_expl
            
            if st.button("🗑️ Supprimer cette question", key=f"del_{idx}"):
                st.session_state["questions"].pop(idx)
                st.rerun()

# --- Affichage des échecs ---
if st.session_state["echecs"]:
    st.markdown("---")
    st.subheader("Questions Abandonnées (Échec d'audit après 2 tentatives)")
    for fail in st.session_state["echecs"]:
        st.error(f"**Question :** {fail['question']}\n\n**Motif de rejet :** {fail['motif_final']}")

# --- Export ---
st.markdown("---")
st.subheader("Export")
if st.session_state["questions"]:
    col_export1, col_export2 = st.columns(2)
    
    with col_export1:
        export_path_wooflash = "export_wooflash.xlsx"
        exporter.exporter_vers_excel(st.session_state["questions"], export_path_wooflash)
        
        with open(export_path_wooflash, "rb") as f:
            st.download_button(
                label="📥 Télécharger l'export Excel (Format Wooflash)",
                data=f,
                file_name="questions_wooflash.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )
            
    with col_export2:
        export_path_wooclap = "export_wooclap.xlsx"
        exporter.exporter_vers_wooclap(st.session_state["questions"], export_path_wooclap)
        
        with open(export_path_wooclap, "rb") as f:
            st.download_button(
                label="📥 Télécharger l'export Excel (Format Wooclap)",
                data=f,
                file_name="questions_wooclap.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="secondary"
            )
