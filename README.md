# AI-Powered Cybersecurity Framework for Smart Grids

🏆 2nd Place Winning Final Year Project

A real-time smart grid cybersecurity platform built using Unity, Firebase, Python, and AI-driven anomaly detection. The system simulates cyber attacks against critical power infrastructure and demonstrates automated threat detection, defense activation, and grid recovery mechanisms.

## Tech Stack

- Unity 3D
- Firebase Realtime Database
- Python
- C#
- Tkinter
- Machine Learning
- Cybersecurity Simulation

## Key Features

- Real-time smart grid simulation
- Operator monitoring dashboard
- Cyber attack simulation console
- AI-based anomaly detection
- Automated defense mechanisms
- Smart meter monitoring
- Grid stability analysis
- Attack mitigation and recovery


## Project Overview

Modern smart grids are increasingly vulnerable to cyber attacks such as meter tampering, load injection, reconnaissance attacks, and large-scale blackouts.

This project demonstrates how artificial intelligence and layered cybersecurity defenses can be used to detect, analyze, and mitigate threats against critical power infrastructure.

The system consists of a Unity-based smart grid simulation, a Firebase communication layer, an operator dashboard for monitoring grid health, and a cyber attack console used to simulate malicious activity.

## System Components

### Unity Smart Grid Simulation
Simulates a smart city power grid with smart meters, lights, generation systems, and real-time grid behavior.

### Operator Dashboard
A Python-based monitoring console that allows operators to monitor grid status, activate defenses, and analyze threats.

### Cyber Attack Console
A Python-based attacker interface used to simulate cyber attacks such as blackouts, meter tampering, load injection, and reconnaissance attacks.

### AI Threat Detection Engine
Analyzes grid load patterns, generation data, and defense status to calculate risk scores and identify anomalous behavior.

### Firebase Realtime Database
Acts as the communication layer between the simulation, dashboards, and attack modules.

## System Architecture

```text
Cyber Attack Console
        │
        ▼
Firebase Realtime Database
        │
 ┌──────┼────────────────────┐
 ▼                           ▼
Unity Smart Grid    Operator Dashboard
Simulation          (Monitoring & Control)
                         │
                         ▼
                  AI Detection Engine
                         │
                         ▼
                  Defense Mechanisms
                  • Authentication Gateway
                  • Temporal Firewall
                  • Anomaly Detection

```

## Cyber Attacks Simulated

- Meter Tampering Attack
- Targeted Blackout Attack
- Grid-Wide Blackout Attack
- Load Injection Attack
- Grid Instability Attack
- Reconnaissance / Data Interception Attack

Each attack is launched through a dedicated attacker console and transmitted through Firebase to the Unity smart grid simulation.

## Defense Mechanisms

The platform implements multiple defensive layers:

- Authentication Gateway
- Temporal Firewall
- AI-Based Anomaly Detection
- Automated Threat Analysis
- Grid Recovery Mechanisms

The operator can enable and disable defenses in real time through the monitoring dashboard.

## AI Threat Detection Engine

The AI module continuously evaluates:

- Grid load changes
- Power generation levels
- System stability
- Active defense status

The engine generates:

- Risk Score (0–100)
- Threat Classification
- Recommended Response Actions

This allows operators to identify abnormal grid behavior before critical failures occur.
