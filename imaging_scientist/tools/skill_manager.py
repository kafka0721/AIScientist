"""Skill management tool (LangChain @tool wrapper)."""

from typing import Literal

from langchain_core.tools import tool


@tool(parse_docstring=True)
def skill_manager(
    action: Literal["install", "list", "search", "uninstall", "info", "browse"],
    source: str = "",
    name: str = "",
    tag: str = "",
    query: str = "",
    limit: int = 30,
    offset: int = 0,
    include_system: bool = False,
) -> str:
    """Manage skills: search installed skills, install from GitHub or local path, list skills, browse remote skills, get details, or uninstall.

    Actions and required parameters:

    action="install" (requires source):
      Install a skill. The source can be:
      - GitHub shorthand: "owner/repo@skill-name" (e.g. "anthropics/skills@peft")
      - GitHub URL: "https://github.com/owner/repo/tree/main/skill-name"
      - Local path: "./my-skill" or "/path/to/skill"
      Nested skills are auto-resolved — if the skill is not at the repo root, subdirectories are searched automatically.

    action="list":
      List installed skills. By default only shows user-installed skills. The
      result is paginated because large skill libraries exceed tool-output
      limits; use `offset` to see another page. For task matching, prefer
      action="search" over paging the complete library.
      Set include_system=True to also show built-in system skills.
      Built-in skills evolve over time, so use action="list" to see the current set.

    action="search" (requires query):
      Search already-installed skills by a short English task description.
      Use this for a specialized task before claiming no local skill fits. It
      returns a small ranked result set; then read the selected skill's
      `/skills/<name>/SKILL.md` instructions.

    action="browse" (optional tag):
      Browse available skills from the EvoSkills repository (EvoScientist/EvoSkills).
      Set tag to filter by category (e.g. tag="core", tag="writing", tag="experiments").
      Returns skill names, descriptions, tags, and install sources you can pass to action="install".

    action="info" (requires name):
      Get details (description, source, path, tags) about a specific skill by name.
      Searches both user and system skills.

    action="uninstall" (requires name):
      Remove a user-installed skill by name. System skills cannot be uninstalled.

    Args:
        action: The operation to perform — "install", "list", "search", "browse", "info", or "uninstall"
        source: Required for install — GitHub shorthand, GitHub URL, or local directory path
        name: Required for info and uninstall — the skill name (for example, one returned by action="list")
        tag: Optional for browse — filter by tag (e.g. "core", "writing", "experiments", "research")
        query: Required for search — short English task keywords
        limit: Maximum skills to display for list (default 30, maximum 100)
        offset: Zero-based list offset for list pagination
        include_system: Only for list — set True to include built-in system skills in the output

    Returns:
        Result message
    """
    from .skills_manager import (
        fetch_remote_skill_index,
        get_skill_info,
        install_skill,
        list_skills,
        uninstall_skill,
    )

    if action == "install":
        if not source:
            return (
                "Error: 'source' is required for install action. "
                "Provide a GitHub shorthand (e.g. source='owner/repo@skill-name'), "
                "a GitHub URL, or a local directory path."
            )
        result = install_skill(source)
        if result["success"]:
            return (
                f"Successfully installed skill: {result['name']}\n"
                f"Description: {result.get('description', '(none)')}\n"
                f"Path: {result['path']}\n\n"
                f"Read its SKILL.md for full instructions."
            )
        else:
            return f"Failed to install skill: {result['error']}"

    elif action == "list":
        skills = list_skills(include_system=include_system)
        if not skills:
            if include_system:
                return "No skills found."
            return "No user skills installed. Use action='install' to add skills, or set include_system=True to see built-in skills."
        user_skills = [
            s for s in skills if s.source in ("workspace", "global", "terminal")
        ]
        system_skills = [s for s in skills if s.source == "builtin"]
        page_size = max(1, min(limit, 100))
        start = max(0, offset)
        lines = []
        if user_skills:
            page = user_skills[start : start + page_size]
            end = start + len(page)
            lines.append(
                f"User Skills ({len(user_skills)}): showing {start + 1}-{end}"
            )
            for skill in page:
                tags_str = f" [{', '.join(skill.tags)}]" if skill.tags else ""
                description = skill.description
                if len(description) > 180:
                    description = description[:177].rstrip() + "..."
                lines.append(f"  - {skill.name}: {description}{tags_str}")
            if end < len(user_skills):
                lines.append(
                    f"  ... {len(user_skills) - end} more. "
                    f"Next page: action='list', offset={end}."
                )
        if system_skills:
            if lines:
                lines.append("")
            lines.append(f"System Skills ({len(system_skills)}):")
            for skill in system_skills:
                tags_str = f" [{', '.join(skill.tags)}]" if skill.tags else ""
                lines.append(f"  - {skill.name}: {skill.description}{tags_str}")
        if user_skills:
            lines.append(
                "Use action='search' with concise English task keywords to find a relevant skill."
            )
        return "\n".join(lines)

    elif action == "search":
        if not query.strip():
            return "Error: 'query' is required for search. Use concise English task keywords."
        from .skills_manager import search_installed_skills

        matches = search_installed_skills(query, include_system=True)
        if not matches:
            return f"No installed skills match: {query}"
        lines = [f"Matching installed skills ({len(matches)}):"]
        for skill in matches:
            tags_str = f" [{', '.join(skill.tags)}]" if skill.tags else ""
            lines.append(f"  - {skill.name}: {skill.description}{tags_str}")
            lines.append(f"    Read: /skills/{skill.name}/SKILL.md")
        return "\n".join(lines)

    elif action == "browse":
        try:
            index = fetch_remote_skill_index()
        except Exception as e:
            return f"Failed to fetch skill index: {e}"
        if tag:
            tag_lower = tag.lower()
            index = [
                s for s in index if tag_lower in [t.lower() for t in s.get("tags", [])]
            ]
        if not index:
            return f"No skills found{' with tag: ' + tag if tag else ''}."
        lines = [f"Available Skills ({len(index)}):"]
        for s in index:
            tags_str = " · ".join(s.get("tags", []))
            lines.append(f"  - {s['name']}: {s['description']}")
            if tags_str:
                lines.append(f"    Tags: {tags_str}")
            lines.append(
                f"    Install: skill_manager(action='install', source='{s['install_source']}')"
            )
        return "\n".join(lines)

    elif action == "uninstall":
        if not name:
            return (
                "Error: 'name' is required for uninstall action. "
                "Use action='list' first to see installed skill names."
            )
        result = uninstall_skill(name)
        if result["success"]:
            return f"Successfully uninstalled skill: {name}"
        else:
            return f"Failed to uninstall skill: {result['error']}"

    elif action == "info":
        if not name:
            return (
                "Error: 'name' is required for info action. "
                "Use action='list' with include_system=True to see all available skill names."
            )
        info = get_skill_info(name)
        if not info:
            return (
                f"Skill not found: {name}. "
                f"Use action='list' with include_system=True to see all available skills."
            )
        tags_str = f"\nTags: {', '.join(info.tags)}" if info.tags else ""
        return (
            f"Name: {info.name}\n"
            f"Description: {info.description}\n"
            f"Source: {info.source}\n"
            f"Path: {info.path}{tags_str}"
        )

    else:
        return f"Unknown action: {action}. Use 'install', 'list', 'browse', 'uninstall', or 'info'."
