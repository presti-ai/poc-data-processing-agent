import io
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from p24_agent_node_poc.agent import process_data
from p24_agent_node_poc.test_case_configs import TEST_CASES, load_variant_inputs


def _load_main_dataset(file) -> Optional[pd.DataFrame]:
    if file is None:
        return None

    name = file.name.lower()
    try:
        if name.endswith(".csv"):
            return pd.read_csv(file)
        if name.endswith(".xlsx") or name.endswith(".xls"):
            return pd.read_excel(file)

        try:
            return pd.read_csv(file)
        except Exception:
            file.seek(0)
            return pd.read_excel(file)
    except Exception as exc:
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


def _render_message_panel(messages: List[Dict[str, str]]) -> None:
    st.subheader("Agent Discussion")
    if not messages:
        st.info("Run the agent to display system, assistant, and tool messages.")
        return

    for idx, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        msg_type = msg.get("type", "text")
        text = msg.get("display", "")
        with st.chat_message("assistant"):
            with st.expander(f"#{idx + 1} | role={role} | type={msg_type}", expanded=False):
                st.markdown(text or "(empty message)")


def render_manual_page() -> None:
    st.title("Manual Agent Run")
    st.write(
        "Upload your own datasets, define the output schema, and run the agent. "
        "This is the original free-form page moved into multipage mode."
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
            key="manual_model_name",
        )

    col_left, col_right = st.columns([2, 1])

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
            help="Describe constraints, extraction rules, and expected output behavior.",
            key="manual_additional_instructions",
        )

        st.subheader("Additional files (any type)")
        uploaded_files = st.file_uploader(
            "Upload one or more files",
            accept_multiple_files=True,
            key="extra_files",
        )

        st.subheader("Output schema")
        schema_rows = st.session_state.get("output_schema", [])

        add_col, remove_col = st.columns(2)
        with add_col:
            if st.button("Add column", key="manual_add_column"):
                schema_rows.append({"name": "", "description": ""})
        with remove_col:
            if st.button("Remove last column", key="manual_remove_column") and len(schema_rows) > 1:
                schema_rows.pop()

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
        run_clicked = st.button("Run agent", type="primary", key="manual_run")

        if run_clicked:
            output_columns = _build_output_columns()
            if not output_columns:
                st.error("Please define at least one output column (with a name).")
            else:
                main_dataset_df = _load_main_dataset(main_file)
                extra_files: List[Tuple[str, bytes]] = []
                for file in uploaded_files or []:
                    try:
                        content = file.getvalue()
                    except Exception:
                        content = io.BytesIO(file.read()).getvalue()
                    extra_files.append((file.name, content))

                with st.spinner("Running agent... this may take a few minutes."):
                    try:
                        result_df, messages = process_data(
                            inputs=None,
                            output_columns=output_columns,
                            additional_instructions=additional_instructions or None,
                            model_name=model_name,
                            main_dataset=main_dataset_df,
                            files=extra_files,
                        )
                    except Exception as exc:
                        st.error(f"Agent run failed: {exc}")
                    else:
                        st.session_state["manual_result_df"] = result_df
                        st.session_state["manual_messages"] = messages

        if "manual_result_df" in st.session_state:
            result_df = st.session_state["manual_result_df"]
            st.success("Agent run completed.")
            st.subheader("Output")
            st.dataframe(result_df)
            csv_bytes = result_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Download output as CSV",
                data=csv_bytes,
                file_name="output.csv",
                mime="text/csv",
                key="manual_download",
            )

    with col_right:
        _render_message_panel(st.session_state.get("manual_messages", []))


def render_test_case_page(case_key: str) -> None:
    config = TEST_CASES[case_key]
    state_prefix = f"{case_key}_state"

    st.title(config.title)
    st.write(config.description)

    with st.sidebar:
        st.header("Run configuration")
        model_name = st.text_input(
            "Model name",
            value="google_genai:gemini-3-flash-preview",
            key=f"{state_prefix}_model",
        )
        variant = st.radio(
            "Scenario",
            options=["small", "large"],
            format_func=lambda value: "Small debug set" if value == "small" else "Large batch (100 rows)",
            key=f"{state_prefix}_variant",
        )

    loaded_inputs = load_variant_inputs(case_key, variant)

    col_left, col_right = st.columns([2, 1])

    with col_left:
        st.subheader("Inputs")
        for label, df in loaded_inputs:
            with st.expander(f"{label} ({len(df)} rows)", expanded=False):
                st.dataframe(df)

        st.subheader("Target output schema")
        st.dataframe(pd.DataFrame(config.output_columns))

        additional_instructions = st.text_area(
            "Additional instructions",
            value=config.additional_instructions,
            key=f"{state_prefix}_instructions",
            height=120,
        )

        run_clicked = st.button("Run this test case", type="primary", key=f"{state_prefix}_run")
        if run_clicked:
            main_dataset = loaded_inputs[0][1]
            extra_inputs = [df for _, df in loaded_inputs[1:]]
            with st.spinner("Running agent... this may take a few minutes."):
                try:
                    result_df, messages = process_data(
                        inputs=extra_inputs or None,
                        output_columns=config.output_columns,
                        additional_instructions=additional_instructions or None,
                        model_name=model_name,
                        main_dataset=main_dataset,
                    )
                except Exception as exc:
                    st.error(f"Agent run failed: {exc}")
                else:
                    st.session_state[f"{state_prefix}_result_df"] = result_df
                    st.session_state[f"{state_prefix}_messages"] = messages

        if f"{state_prefix}_result_df" in st.session_state:
            result_df = st.session_state[f"{state_prefix}_result_df"]
            st.subheader("Output")
            st.dataframe(result_df)
            csv_bytes = result_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Download output CSV",
                data=csv_bytes,
                file_name=f"{case_key}_{variant}_output.csv",
                mime="text/csv",
                key=f"{state_prefix}_download",
            )

    with col_right:
        _render_message_panel(st.session_state.get(f"{state_prefix}_messages", []))
