## Cost constraints
- Each run has a $50 hard limit (enforced automatically — over-budget 
  runs get error_rate 999 and are always reverted)
- You have 10 total experiments
- Total budget across all experiments is capped

Keep prompts efficient. Avoid instructions that cause excessive 
browser steps — long retry loops, unnecessary verification passes, 
or verbose step-by-step reasoning that inflates token count. 
A typical successful run costs $25-35.