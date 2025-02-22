"""Generate requirements.txt from pyproject.toml dependencies"""
import tomli
import os

def generate_requirements():
    # Read pyproject.toml
    with open("pyproject.toml", "rb") as f:
        pyproject = tomli.load(f)
    
    # Extract dependencies
    dependencies = pyproject.get("project", {}).get("dependencies", [])
    
    # Format dependencies (remove version constraints)
    formatted_deps = []
    for dep in dependencies:
        # Extract package name without version
        package = dep.split(">=")[0].strip()
        formatted_deps.append(package)
    
    # Write requirements.txt
    with open("requirements.txt", "w") as f:
        for dep in sorted(formatted_deps):
            f.write(f"{dep}\n")

if __name__ == "__main__":
    generate_requirements()
    print("requirements.txt has been generated successfully!")
