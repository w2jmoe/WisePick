# WisePick API Archive

This directory preserves the historical evolution of WisePick API, documenting the journey from initial concept to the current v0 implementation. 

## Purpose

These files are not used in the current production code but have significant historical and educational value. They record:

- **Early experimental designs** that shaped the current architecture
- **Architectural evolution** from simple routing to data-driven decisions  
- **Project planning** that guided the development process
- **Technical decisions** that informed the current implementation

## Directory Structure

### `early_experiments/`
Early experimental designs that explored advanced concepts:

- `decision_dataset.py` - Early data collection table design
- `decision_dataset_writer.py` - Complete data collection service

**Historical significance**: These files represent the first exploration of **shared decision memory** and **collective tool experience** concepts that are foundational to WisePick's long-term vision.

### `deprecated_models/`
Deprecated data models showing architectural evolution:

- `decision_log.py` - First-generation decision logging system

**Historical significance**: Shows the evolution from simple logging to structured decision records with full auditability.

### `project_planning/`
Project planning and architecture documentation:

- `implementation_plan.md` - Detailed implementation roadmap
- `architecture.md` - System architecture design

**Historical significance**: Complete record of the technical decision-making process and project evolution.

## Why These Files Are Preserved

### 1. Record of Evolution
These files document WisePick's journey from **rule-driven routing** to **data-driven decision systems**. They show:

- How bootstrap rules evolved into the current scoring algorithm
- The transition from individual trial-and-error to collective experience
- The architectural thinking behind shared decision memory

### 2. Future Reference
While not used in v0, these designs provide valuable reference for:

- **Future Cloud versions** - Data collection and aggregation patterns
- **Shared decision memory layer** - Early exploration of collective intelligence
- **Architectural scaling** - Lessons from early design decisions

### 3. Educational Value
For developers understanding the project:

- Shows the thinking behind current design decisions
- Demonstrates architectural trade-offs and evolution
- Provides context for why certain approaches were chosen

## Connection to Current Implementation

### From Experiment to Production

The concepts explored in these archived files have influenced the current v0 implementation:

- **Data-driven decisions**: Early data collection ideas evolved into the current feedback-driven scoring
- **Shared experience**: The vision of collective tool experience informs the bootstrap decay mechanism
- **Auditability**: Early logging concepts shaped the current explain and trace systems

### Future Vision

These archives lay the groundwork for future developments:

- **Shared decision memory**: Building on early data collection concepts
- **Collective tool experience**: Realizing the vision of agents learning from each other
- **Cloud architecture**: Scaling patterns explored in early designs

## Note to Developers

These files are preserved for historical and educational purposes. They are not required for the current v0 implementation and should not be imported or referenced in production code.

For current development, refer to the main codebase in the parent directory.
