import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
import schemas

def exporter_vers_excel(questions: list[schemas.QuestionModel], output_path: str):
    """
    Exporte la liste de questions vers un fichier Excel compatible avec Wooflash.
    """
    rows = []
    
    for q in questions:
        row = {
            'Type of question': '',
            'Question': q.intitule,
            'Answer': '',
            'Feedback': q.explication_pedagogique,
            'Content': ''
        }
        
        options = []
        
        if q.type == "ouverte":
            row['Type of question'] = 'Essay'
            row['Answer'] = q.reponse_attendue
            
        elif q.type == "qcm":
            row['Type of question'] = 'SCQ'
            if q.justification_distracteurs:
                row['Feedback'] += "\n\n" + q.justification_distracteurs
            
            options = q.options if q.options else []
            
            try:
                idx = options.index(q.reponse_attendue) + 1
                row['Answer'] = str(idx)
            except ValueError:
                row['Answer'] = '1'
                if q.reponse_attendue not in options:
                    options.insert(0, q.reponse_attendue)
            
        if options and len(options) > 0:
            row['Content'] = options[0]
            
        for i, opt in enumerate(options[1:], start=1):
            col_name = f'Unnamed: {i+4}'
            row[col_name] = opt
            
        rows.append(row)
        
    df = pd.DataFrame(rows)
    
    base_cols = ['Type of question', 'Question', 'Answer', 'Feedback', 'Content']
    other_cols = [c for c in df.columns if c not in base_cols]
    df = df[base_cols + sorted(other_cols, key=lambda x: int(x.split(':')[1]) if ':' in x else 0)]
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    
    headers = []
    for col in df.columns:
        if col.startswith('Unnamed:'):
            headers.append('')
        else:
            headers.append(col)
    ws.append(headers)
    
    for r in dataframe_to_rows(df, index=False, header=False):
        ws.append(r)
        
    wb.save(output_path)

def exporter_vers_wooclap(questions: list[schemas.QuestionModel], output_path: str):
    """
    Exporte la liste de questions vers un fichier Excel compatible avec Wooclap.
    """
    rows = []
    
    for q in questions:
        row = {
            'Type': '',
            'Title': q.intitule,
            'Correct': ''
        }
        
        options = []
        
        if q.type == "ouverte":
            # Pour Wooclap, une question ouverte classique ne prend pas de choix.
            # L'attendu et le feedback ne sont pas gérés de la même manière dans l'import Wooclap basique.
            row['Type'] = 'OpenQuestion'
            
        elif q.type == "qcm":
            row['Type'] = 'MCQ'
            options = q.options if q.options else []
            
            try:
                idx = options.index(q.reponse_attendue) + 1
                row['Correct'] = str(idx)
            except ValueError:
                row['Correct'] = '1'
                if q.reponse_attendue not in options:
                    options.insert(0, q.reponse_attendue)
            
        for i, opt in enumerate(options):
            col_name = f'Choice_{i+1}'
            row[col_name] = opt
            
        rows.append(row)
        
    df = pd.DataFrame(rows)
    
    # Assurer l'ordre des colonnes de base
    base_cols = ['Type', 'Title', 'Correct']
    other_cols = [c for c in df.columns if c not in base_cols]
    
    # Trier les colonnes Choice_1, Choice_2, etc.
    other_cols_sorted = sorted(other_cols, key=lambda x: int(x.split('_')[1]) if '_' in x else 0)
    df = df[base_cols + other_cols_sorted]
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Questions"
    
    # Écrire les en-têtes. Pour les choix, l'en-tête est "Choice" répété.
    headers = []
    for col in df.columns:
        if col.startswith('Choice_'):
            headers.append('Choice')
        else:
            headers.append(col)
    ws.append(headers)
    
    for r in dataframe_to_rows(df, index=False, header=False):
        ws.append(r)
        
    wb.save(output_path)
