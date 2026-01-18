from pathlib import Path
from jinja2 import Environment, FileSystemLoader

class PromptService:
    def __init__(self, prompts_dir: str = "src/prompts"):
        # Ensure we can find the prompts directory relative to the project root
        # If running from root, "src/prompts" should work.
        # Ideally we use an absolute path based on __file__.
        
        base_path = Path(__file__).resolve().parent.parent / "prompts"
        if not base_path.exists():
            # Fallback if structure is different
            base_path = Path("src/prompts").resolve()
            
        self.env = Environment(loader=FileSystemLoader(str(base_path)))

    def render_prompt(self, template_name: str, **kwargs) -> str:
        template = self.env.get_template(template_name)
        return template.render(**kwargs)

prompt_service = PromptService()
