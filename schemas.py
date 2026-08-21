from pydantic import BaseModel, Field, model_validator
from typing import Literal, Optional, List

class QuestionModel(BaseModel):
    id: int
    type: Literal["ouverte", "qcm"]
    processus_bloom: Literal["interpreter", "exemplifier", "resumer", "inferer", "comparer", "expliquer"]
    intitule: str
    reponse_attendue: str
    explication_pedagogique: str = Field(description="Feedback direct à l'étudiant (tutoiement, STRICTEMENT NEUTRE sur la justesse car toujours affiché, concis)")
    options: Optional[List[str]] = Field(default=None, description="Exactement 4 propositions si type == 'qcm'")
    justification_distracteurs: Optional[str] = Field(default=None, description="Explication des biais ciblés par les distracteurs (adressée à l'étudiant, tutoiement, STRICTEMENT NEUTRE sur la justesse)")
    strategie_pedagogique: str = Field(description="Quelques lignes pour l'enseignant expliquant la stratégie pédagogique de cette question")

    @model_validator(mode="after")
    def verifier_coherence_type(self) -> "QuestionModel":
        if self.type == "qcm":
            if not self.options or len(self.options) != 4:
                raise ValueError("Une question de type 'qcm' doit comporter exactement 4 options.")
            if not self.justification_distracteurs:
                raise ValueError("Une question de type 'qcm' doit comporter une justification_distracteurs.")
            if self.reponse_attendue not in self.options:
                raise ValueError("La reponse_attendue d'un qcm doit figurer exactement parmi les options fournies.")
        elif self.type == "ouverte":
            if self.options is not None:
                raise ValueError("Une question ouverte ne doit pas comporter d'options.")
        return self

class VerdictAudit(BaseModel):
    id: int
    verdict: Literal["VALIDE", "REJETE"]
    motif_rejet: Optional[str] = None
    consigne_correction: Optional[str] = None
