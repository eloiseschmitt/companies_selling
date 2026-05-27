from sqladmin import Admin, ModelView
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from app import app
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
engine = create_engine(f"sqlite:///{os.path.join(BASE_DIR, 'companies.db')}")


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    siret: Mapped[str] = mapped_column(primary_key=True)
    nic: Mapped[str]
    dateCreationEtablissement: Mapped[str]
    trancheEffectifsEtablissement: Mapped[str]
    activitePrincipaleEtablissement: Mapped[str]


admin = Admin(app, engine)


class CompanyAdmin(ModelView, model=Company):
    column_list = [
        Company.siret,
        Company.nic,
        Company.dateCreationEtablissement,
        Company.trancheEffectifsEtablissement,
        Company.activitePrincipaleEtablissement,
    ]
    column_searchable_list = [
        Company.siret,
        Company.activitePrincipaleEtablissement,
    ]
    column_sortable_list = [
        Company.siret,
        Company.dateCreationEtablissement,
        Company.trancheEffectifsEtablissement,
        Company.activitePrincipaleEtablissement,
    ]
    column_labels = {
        Company.siret: "SIRET",
        Company.nic: "NIC",
        Company.dateCreationEtablissement: "Date de création",
        Company.trancheEffectifsEtablissement: "Tranche d'effectifs",
        Company.activitePrincipaleEtablissement: "Activité principale",
    }
    can_create = False
    can_edit = False
    can_delete = False
    name_plural = "Companies"


admin.add_view(CompanyAdmin)
