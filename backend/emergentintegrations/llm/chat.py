class LlmChat:
    def __init__(self, *args, **kwargs): pass
    def with_model(self, *args, **kwargs): return self
    def with_system_prompt(self, *args, **kwargs): return self
    async def send_message(self, *args, **kwargs): return 'Mock response'

class UserMessage:
    def __init__(self, text=''): self.text = text
