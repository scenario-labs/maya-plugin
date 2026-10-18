"""Team and project choice without UI (spec 4.10, step 3).

One team with one project is chosen without asking; a saved choice that still
exists is kept; otherwise the caller asks the person.
"""

from __future__ import annotations


def load(backend) -> list:
    """Teams with their projects (blocking: call from a worker)."""
    teams = backend.teams()
    for team in teams:
        if not isinstance(team.get("projects"), list):
            team["projects"] = backend.projects(team.get("id", ""))
    return [team for team in teams if team.get("id")]


def automatic_choice(teams: list, team_id: str = "", project_id: str = ""):
    """``(team, project)`` when no question is needed, else ``None``."""
    for team in teams:
        for project in team.get("projects") or []:
            if team.get("id") == team_id and project.get("id") == project_id:
                return team, project
    if len(teams) == 1 and len(teams[0].get("projects") or []) == 1:
        return teams[0], teams[0]["projects"][0]
    return None
