import streamlit as st
from google import genai
from google.genai import types
import time
import schemas
import json
import base64
from contextlib import contextmanager
import tempfile
import os

@contextmanager
def gerer_pdf_gemini(client: genai.Client, pdf_bytes: bytes, display_name: str = "document.pdf"):
    taille_mo = len(pdf_bytes) / (1024 * 1024)
    if taille_mo < 15:
        part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
        yield part
    else:
        uploaded_file = None
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                temp_file.write(pdf_bytes)
                temp_path = temp_file.name
                
            uploaded_file = client.files.upload(file=temp_path, config={'display_name': display_name})
            
            while uploaded_file.state.name == "PROCESSING":
                time.sleep(2)
                uploaded_file = client.files.get(name=uploaded_file.name)
                
            if uploaded_file.state.name == "FAILED":
                raise ValueError("Le traitement du PDF par Gemini a échoué.")
                
            yield uploaded_file
        finally:
            if uploaded_file:
                try:
                    client.files.delete(name=uploaded_file.name)
                except Exception as e:
                    print(f"Erreur lors de la suppression du fichier distant : {e}")
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

def executer_appel_gemini(client: genai.Client, contents: list, response_schema=None, system_instruction: str = None):
    # En première intention : 3.1 flash lite, en fallback : 2.5 flash
    model_nominal = "gemini-3.1-flash-lite"
    model_secours = "gemini-2.5-flash"
    
    config = types.GenerateContentConfig(
        temperature=0.2,
        system_instruction=system_instruction,
    )
    if response_schema:
        config.response_mime_type = "application/json"
        config.response_schema = response_schema
        
    for tentative in range(1, 4):
        try:
            response = client.models.generate_content(
                model=model_nominal,
                contents=contents,
                config=config
            )
            _cumuler_tokens(response)
            if "logs" in st.session_state:
                st.session_state["logs"].append(f"[Succès] Appel {model_nominal} réussi (Tentative {tentative}).")
            return response
        except Exception as e:
            if "logs" in st.session_state:
                st.session_state["logs"].append(f"[Erreur] {model_nominal} tentative {tentative} échouée : {str(e)}")
            time.sleep(2 ** tentative)
            
    try:
        if "logs" in st.session_state:
            st.session_state["logs"].append(f"[Bascule] Passage sur le modèle de secours {model_secours}.")
        response = client.models.generate_content(
            model=model_secours,
            contents=contents,
            config=config
        )
        _cumuler_tokens(response)
        return response
    except Exception as e:
        msg = f"[Erreur Fatale] Le modèle de secours {model_secours} a également échoué : {str(e)}"
        if "logs" in st.session_state:
            st.session_state["logs"].append(msg)
        st.error(msg)
        st.stop()

def _cumuler_tokens(response):
    if hasattr(response, 'usage_metadata') and response.usage_metadata:
        in_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0)
        out_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0)
        if "tokens_utilises" in st.session_state:
            st.session_state["tokens_utilises"]["in"] += in_tokens
            st.session_state["tokens_utilises"]["out"] += out_tokens

def generer_lot_questions(client: genai.Client, document_part, nb_questions: int, type_selectionne: str, contexte_ciblage: str = "") -> list[schemas.QuestionModel]:
    system_prompt = f"""Tu es un concepteur pédagogique expert de la taxonomie de Bloom révisée pour des étudiants de niveau Master.
Ta mission est de générer {nb_questions} questions ciblant EXCLUSIVEMENT le niveau "Compréhension".
Le type de question autorisé pour ce lot est strictement : {type_selectionne}.

Consignes STRICTES :
1. Ancrage : Base-toi uniquement sur le document fourni (et la partie ciblée si précisée). Zéro extrapolation externe.
2. BANNISSEMENT ABSOLU de la mémorisation (Test anti-Ctrl+F) : Il est formellement interdit de demander une définition textuelle, un acronyme, une date ou un fait isolé. L'étudiant ne doit pas pouvoir répondre en ayant simplement appris par cœur. Il doit mobiliser un modèle mental (expliciter une chaîne causale, déduire une conséquence).
3. FORME DE LA QUESTION : NE FAIS JAMAIS MENTION du document ("D'après le document...", "Dans le texte..."). La question doit être 100% autonome et directe.
4. FEEDBACK ÉTUDIANT (explication_pedagogique / justification_distracteurs) : Rédige-les DIRECTEMENT pour l'étudiant. Utilise un ton bienveillant, amical et utilise le TUTOIEMENT. ATTENTION : Ce feedback s'affichera quelle que soit la réponse de l'étudiant (juste ou fausse). Il doit donc être STRICTEMENT NEUTRE quant à la justesse de sa réponse (Pas de "Bravo", "C'est juste", "Tu as faux", etc.). Contente-toi d'expliquer le concept objectivement. Sois extrêmement concis pour aller à l'essentiel.
5. STRATÉGIE (strategie_pedagogique) : Explique ici à l'enseignant pourquoi cette question est pertinente et ce qu'elle évalue.
6. Sois concis et percutant dans la rédaction."""

    prompt = f"Génère {nb_questions} questions de type {type_selectionne} à partir de ce document en respectant scrupuleusement les consignes système."
    if contexte_ciblage:
        prompt += f"\n\nCONTRAINTE DE CIBLAGE : Concentre-toi impérativement sur la partie ou le sujet suivant : {contexte_ciblage}"
        
    response = executer_appel_gemini(
        client=client,
        contents=[document_part, prompt],
        response_schema=list[schemas.QuestionModel],
        system_instruction=system_prompt
    )
    
    if hasattr(response, 'parsed') and response.parsed:
        return response.parsed
        
    questions = []
    if response.text:
        try:
            data = json.loads(response.text)
            for item in data:
                try:
                    questions.append(schemas.QuestionModel(**item))
                except:
                    pass
        except:
            pass
    return questions

def auditer_questions(client: genai.Client, document_part, questions: list[schemas.QuestionModel], contexte_ciblage: str = "") -> list[schemas.VerdictAudit]:
    system_prompt = """Tu es un auditeur pédagogique impitoyable de niveau Master.
Critères d'élimination stricts (Si OUI -> REJET) :
1. Test Ctrl+F (Anti-mémorisation) : La réponse est-elle trouvable mot pour mot dans le cours ? Fait-elle appel à du pur par cœur (définition, date, acronyme) ? -> REJET.
2. Test de dérive Bloom : La question relève-t-elle du Niveau 1 (Rappel passif / Mémorisation) au lieu du Niveau 2 (Compréhension / Explication de mécanismes) ? -> REJET absolu.
3. Test du saut logique : Manque-t-il l'explicitation du mécanisme (A entraîne B) ? -> REJET.
4. Test hors corpus : Hors document ? -> REJET.
5. La question fait-elle mention du "document" ou du "texte" au lieu d'être autonome ? -> REJET.
6. Le type de la question est-il incorrect ? -> REJET.

Fournis un verdict (VALIDE ou REJETE) pour chaque question de la liste, en respectant l'ID."""

    questions_json = [q.model_dump() for q in questions]
    prompt = f"Voici les questions à auditer :\n{json.dumps(questions_json, indent=2)}\n\nÉvalue-les rigoureusement."
    if contexte_ciblage:
        prompt += f"\nVérifie aussi qu'elles portent sur le ciblage : {contexte_ciblage}"
    
    response = executer_appel_gemini(
        client=client,
        contents=[document_part, prompt],
        response_schema=list[schemas.VerdictAudit],
        system_instruction=system_prompt
    )
    
    if hasattr(response, 'parsed') and response.parsed:
        return response.parsed
        
    verdicts = []
    if response.text:
        try:
            data = json.loads(response.text)
            for item in data:
                verdicts.append(schemas.VerdictAudit(**item))
        except:
            pass
    return verdicts

def corriger_lot_questions(client: genai.Client, document_part, rejets: list, contexte_ciblage: str = "") -> list[schemas.QuestionModel]:
    """
    Corrige un lot entier de questions rejetées en un seul appel (pour économiser les tokens d'entrée liés au PDF).
    rejets = list de tuples (question_dict, motif, consigne)
    """
    system_prompt = """Tu es un concepteur pédagogique expert.
Ta mission est de corriger un lot de questions qui ont été REJETÉES par l'audit.

ATTENTION - REGLE ABSOLUE :
- Tu NE DOIS EN AUCUN CAS changer le TYPE de la question. Si elle était "qcm", elle doit RESTER "qcm" avec 4 options. Si elle était "ouverte", elle doit RESTER "ouverte".
- Respecte le tutoiement, la concision, et SURTOUT la NEUTRALITÉ ABSOLUE quant à la justesse pour les feedbacks étudiants (ils s'afficheront toujours, juste ou faux, donc pas de "Bravo" ou "Mauvaise réponse").
- Ne fais jamais mention du document source dans l'intitulé de la question.
- La question corrigée ne doit faire appel à aucune mémorisation (Niveau 1 de Bloom). Elle doit obligatoirement tester la compréhension (Niveau 2 : expliciter une chaîne causale, déduire)."""

    infos_rejets = []
    for q_rej, motif, consigne in rejets:
        infos_rejets.append({
            "question_originale": q_rej if isinstance(q_rej, dict) else q_rej.model_dump(),
            "motif_rejet": motif,
            "consigne": consigne
        })
        
    prompt = f"""Les questions suivantes ont été rejetées. Corrige-les une par une, et retourne la liste des questions corrigées (en gardant impérativement leurs IDs et leurs TYPES initiaux).

Liste des rejets :
{json.dumps(infos_rejets, indent=2)}"""

    if contexte_ciblage:
        prompt += f"\n\nRappel du ciblage du cours : {contexte_ciblage}"

    response = executer_appel_gemini(
        client=client,
        contents=[document_part, prompt],
        response_schema=list[schemas.QuestionModel],
        system_instruction=system_prompt
    )
    
    if hasattr(response, 'parsed') and response.parsed:
        return response.parsed
        
    questions_corrigees = []
    if response.text:
        try:
            data = json.loads(response.text)
            for item in data:
                try:
                    questions_corrigees.append(schemas.QuestionModel(**item))
                except:
                    pass
        except:
            pass
    return questions_corrigees
