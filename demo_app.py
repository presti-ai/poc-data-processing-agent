import io
from typing import List, Dict, Tuple, Optional

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from p24_agent_node_poc.agent import process_data


load_dotenv()


def _load_main_dataset(file) -> Optional[pd.DataFrame]:
    if file is None:
        return None

    name = file.name.lower()
    try:
        if name.endswith(".csv"):
            return pd.read_csv(file)
        elif name.endswith(".xlsx") or name.endswith(".xls"):
            return pd.read_excel(file)
        else:
            # Fallback: try CSV first, then Excel
            try:
                return pd.read_csv(file)
            except Exception:
                file.seek(0)
                return pd.read_excel(file)
    except Exception as exc:  # pragma: no cover - UI error reporting
        st.error(f"Failed to load main dataset: {exc}")
        return None


def _build_output_columns() -> List[Dict[str, str]]:
    schema_rows = st.session_state.get("output_schema", [])
    output_columns: List[Dict[str, str]] = []
    for idx, _ in enumerate(schema_rows):
        name = st.session_state.get(f"col_name_{idx}", "").strip()
        description = st.session_state.get(f"col_desc_{idx}", "").strip()
        if name:
            output_columns.append({"name": name, "description": description})
    return output_columns


def main() -> None:
    st.set_page_config(page_title="P24 Agent Demo", layout="wide")
    st.title("P24 Agent Node POC – Demo Interface")
    st.write(
        "Configure a main dataset (optional), upload extra files, define the desired output schema, "
        "and let the agent generate a structured output table."
    )

    if "output_schema" not in st.session_state:
        st.session_state["output_schema"] = [
            {"name": "Column 1", "description": ""},
            {"name": "Column 2", "description": ""},
        ]

    with st.sidebar:
        st.header("Configuration")
        model_name = st.text_input(
            "Model name",
            value="google_genai:gemini-3-flash-preview",
            help="Passed through to the underlying agent.",
        )

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Main dataset (optional)")
        main_file = st.file_uploader(
            "Upload a main CSV/Excel file",
            type=["csv", "xlsx", "xls"],
            key="main_dataset",
        )

        st.subheader("Additional instructions")
        additional_instructions = st.text_area(
            "Guidance for the agent",
            help="You can describe the task, constraints, or any business rules here.",
        )

        st.subheader("Additional files (any type)")
        uploaded_files = st.file_uploader(
            "Upload one or more files",
            accept_multiple_files=True,
            key="extra_files",
        )

    with col_right:
        st.subheader("Output schema")

        schema_rows = st.session_state.get("output_schema", [])

        add_col, remove_col = st.columns(2)
        with add_col:
            if st.button("Add column"):
                schema_rows.append({"name": "", "description": ""})
        with remove_col:
            if st.button("Remove last column") and len(schema_rows) > 1:
                schema_rows.pop()

        # Render editable rows
        for idx, row in enumerate(schema_rows):
            st.text_input(
                f"Column {idx + 1} name",
                value=row.get("name", ""),
                key=f"col_name_{idx}",
            )
            st.text_input(
                f"Column {idx + 1} description",
                value=row.get("description", ""),
                key=f"col_desc_{idx}",
            )
            st.markdown("---")

        st.session_state["output_schema"] = schema_rows

    run_clicked = st.button("Run agent", type="primary")

    if run_clicked:
        output_columns = _build_output_columns()
        if not output_columns:
            st.error("Please define at least one output column (with a name).")
            return

        main_dataset_df = _load_main_dataset(main_file)

        extra_files: List[Tuple[str, bytes]] = []
        for file in uploaded_files or []:
            try:
                content = file.getvalue()
            except Exception:
                # Fallback for file-like objects
                content = io.BytesIO(file.read()).getvalue()
            extra_files.append((file.name, content))

        with st.spinner("Running agent... this may take a few minutes."):
            try:
                result_df, _ = process_data(
                    inputs=None,
                    output_columns=output_columns,
                    additional_instructions=additional_instructions or None,
                    model_name=model_name,
                    main_dataset=main_dataset_df,
                    files=extra_files,
                )
            except Exception as exc:  # pragma: no cover - runtime errors surfaced in UI
                st.error(f"Agent run failed: {exc}")
                return

        st.success("Agent run completed.")
        st.subheader("Result")
        st.dataframe(result_df)

        csv_bytes = result_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download result as CSV",
            data=csv_bytes,
            file_name="output.csv",
            mime="text/csv",
        )


if __name__ == "__main__":
    main()

