from sqladmin import Admin, ModelView
from sqlalchemy import create_engine
from sqlalchemy.sql.expression import Select, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from starlette.requests import Request
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
    denomination_legale: Mapped[str]
    prenom: Mapped[str]
    nom: Mapped[str]


class MultiActivityCodeFilter:
    has_operator = False
    template = "sqladmin/filters/multi_lookup_filter.html"

    def __init__(self):
        self.column = Company.activitePrincipaleEtablissement
        self.title = "Activité principale"
        self.parameter_name = "activitePrincipaleEtablissement"

    async def lookups(self, request: Request, model, run_query):
        rows = await run_query(
            select(self.column)
            .where(self.column.is_not(None), self.column != "")
            .distinct()
            .order_by(self.column)
        )
        return [(row[0], row[0]) for row in rows]

    def selected_values(self, request: Request) -> set[str]:
        raw_value = request.query_params.get(self.parameter_name, "")
        return {value for value in raw_value.split(",") if value}

    def toggle_url(self, request: Request, value: str):
        selected = self.selected_values(request)

        if value in selected:
            selected.remove(value)
        else:
            selected.add(value)

        url = request.url.remove_query_params([self.parameter_name, "page"])
        if not selected:
            return url

        return url.include_query_params(
            **{self.parameter_name: ",".join(sorted(selected))}
        )

    def clear_url(self, request: Request):
        return request.url.remove_query_params([self.parameter_name, "page"])

    async def get_filtered_query(self, query: Select, value, model) -> Select:
        values = [item for item in str(value).split(",") if item]
        if not values:
            return query

        return query.filter(self.column.in_(values))


admin = Admin(app, engine)


class CompanyAdmin(ModelView, model=Company):
    column_list = [
        Company.siret,
        Company.nic,
        Company.denomination_legale,
        Company.prenom,
        Company.nom,
        Company.dateCreationEtablissement,
        Company.trancheEffectifsEtablissement,
        Company.activitePrincipaleEtablissement,
    ]
    column_searchable_list = [
        Company.siret,
        Company.denomination_legale,
        Company.prenom,
        Company.nom,
        Company.activitePrincipaleEtablissement,
    ]
    column_filters = [MultiActivityCodeFilter()]
    column_sortable_list = [
        Company.siret,
        Company.denomination_legale,
        Company.prenom,
        Company.nom,
        Company.dateCreationEtablissement,
        Company.trancheEffectifsEtablissement,
        Company.activitePrincipaleEtablissement,
    ]
    column_labels = {
        Company.siret: "SIRET",
        Company.nic: "NIC",
        Company.denomination_legale: "Dénomination légale",
        Company.prenom: "Prénom",
        Company.nom: "Nom",
        Company.dateCreationEtablissement: "Date de création",
        Company.trancheEffectifsEtablissement: "Tranche d'effectifs",
        Company.activitePrincipaleEtablissement: "Activité principale",
    }
    can_create = False
    can_edit = False
    can_delete = False
    name_plural = "Companies"


admin.add_view(CompanyAdmin)
