# Loan Portfolio Management System

## Overview

This is a loan portfolio management system built with Streamlit for financial institutions or lenders to track and manage their loan operations. The application provides functionality to manage clients, loans, and payment tracking with integrated reporting capabilities. The system is designed as a single-file web application that handles the complete loan lifecycle from client registration to payment tracking and reporting.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend Architecture
- **Streamlit Framework**: Single-page web application using Streamlit for the user interface
- **Interactive Dashboard**: Real-time data visualization and form-based interactions
- **Responsive Design**: Browser-based interface that adapts to different screen sizes

### Backend Architecture
- **Monolithic Design**: Single Python file (`app.py`) containing all application logic
- **Direct Database Access**: No ORM layer, using raw SQL queries for database operations
- **Stateless Sessions**: Leverages Streamlit's session state management for user interactions

### Data Storage
- **SQLite Database**: Local file-based database (`cartera_prestamos.db`) for data persistence
- **Three-Table Schema**:
  - `clientes`: Customer information storage
  - `prestamos`: Loan details and terms
  - `pagos`: Payment history tracking
- **Relational Design**: Foreign key relationships between clients, loans, and payments

### Database Schema Design
- **Clients Table**: Stores customer identification, contact details, and address information
- **Loans Table**: Tracks loan amounts, interest rates, terms, payment frequency, and disbursement dates
- **Payments Table**: Records all payment transactions with dates and amounts
- **Data Integrity**: Foreign key constraints ensure referential integrity between related entities

### Reporting System
- **PDF Generation**: Uses ReportLab library for creating formatted PDF reports
- **Data Export**: Pandas integration for data manipulation and export capabilities
- **Financial Calculations**: Built-in loan amortization and payment schedule calculations

### Authentication and Authorization
- **No Authentication**: Currently operates without user authentication or access control
- **Single-User Design**: Designed for single-user or trusted environment usage

## External Dependencies

### Python Libraries
- **streamlit**: Web application framework for the user interface
- **pandas**: Data manipulation and analysis for handling loan and payment data
- **sqlite3**: Built-in Python database interface (no external database server required)
- **reportlab**: PDF generation library for creating loan reports and documentation
- **datetime**: Python standard library for date and time operations

### Database
- **SQLite**: Embedded database engine, no external database server required
- **Local Storage**: Database file stored locally in the application directory

### Development Environment
- **Python 3.x**: Runtime environment requirement
- **No External APIs**: Self-contained application with no third-party service integrations
- **File System**: Requires local file system access for database and PDF report storage