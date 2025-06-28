## Setup

1. ### Install Dependencies

   Run the following command to install all required Python packages:

   ```bash
   pip install -r requirements.txt
   ```

2. ### Environment Variables

   Create a `.env` file in the `pcb_server/` directory with the following content:

   ```env
   GOOGLE_API_KEY=your_google_api_key_here
   ```

   Your project directory will roughly look like this:

   ```
   .
   ├── accounts
   ├── pcb_manager
   ├── pcb_server
   │   └── .env
   └── static
   ```

3. ### Start the Development Server

   Launch the application with `uvicorn`:

   ```bash
   uvicorn pcb_project.asgi:application --reload
   ```
