# Project Name

this is an application utilizing Large Language Models (LLMs) combined with Gaussian Mixture Modeling (GMM) and Principal Component Analysis (PCA) to generate optimal team compositions for the Valorant Championship Tour (VCT).

## Table of Contents

- [Introduction](#introduction)
- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)

## Introduction

VCT represents the pinnacle of competitions, where the best of the best compete against each other and show off their skills.
Current methods of team formation rely heavily on the experience and intuition of managers, who assess players' skills, roles, and synergy through a time-consuming process.
While statistical analysis has long been a part of traditional sports, the esports scene seems to be a bit behind in this aspect, likely due to the large cost overhead it requires to maintain scouting teams.
The objective here is to find a way to combine well studied classical methods with the natural language capabilities of an LLM to make stats driven team building more accessible and cost-effective to the Valorant community.

## Features

- Use AWS Glue and PySpark to ingest data obtained from Riot Official Database.
- Integrate with 1 Claude Haiku and 2 Claude Sonnet LLM Models as agents on AWS Bedrock for generating output.
- Use Principal Component Analysis and Gaussian Mixture Model to identify key performance factors for each role and generate pdf based on the key factors.

## Installation

Step-by-step instructions on how to set up and run the project.

```bash
# Clone the repository
git clone https://github.com/zhouzhouthezhou/vct_team_manager.git

# Navigate to the project directory
cd vct-teammanager/vct

#Create virtual environment
python3 -m venv myenv
source myenv/bin/activate

# Install dependencies
pip install -r requirements.txt

## Usage
# Start app
streamlit run app.py


```
