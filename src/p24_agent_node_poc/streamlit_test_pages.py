"""
Streamlit UI components: Manual run page, generic test-case page, and UC2 two-phase page.

Renders file uploads, output schema, run buttons, and agent message logs.
"""

import tempfile
from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st
from langchain_core.messages import BaseMessage, messages_to_dict

from p24_agent_node_poc.agent import process_data, process_data_two_phase
from p24_agent_node_poc.test_case_configs import TEST_CASES, load_variant_input_files


def _build_output_columns() -> List[Dict[str, str]]:
    """Collect column names/descriptions from session state (Manual page schema inputs)."""
    schema_rows = st.session_state.get("output_schema", [])
    output_columns: List[Dict[str, str]] = []
    for idx, _ in enumerate(schema_rows):
        name = st.session_state.get(f"col_name_{idx}", "").strip()
        description = st.session_state.get(f"col_desc_{idx}", "").strip()
        if name:
            output_columns.append({"name": name, "description": description})
    return output_columns


def _render_message_panel(messages: List[Dict[str, str]]) -> None:
    """Display agent conversation: human, AI, and tool messages in expandable blocks."""
    st.subheader("Agent Discussion")
    if not messages:
        st.info("Run the agent to display system, assistant, and tool messages.")
        return

    msg_list = messages.get("messages", [])
    if not isinstance(msg_list, list):
        msg_list = []
    # Filter to only LangChain message objects (deepagents stream may include strings/other types)
    valid_msgs = [m for m in msg_list if isinstance(m, BaseMessage)]
    # Convert to dicts and render by role (human/ai/tool)
    for idx, msg in enumerate(messages_to_dict(valid_msgs)):
        try:
            msg = msg.get("data", {})
            text = msg.get("content", "")
            if isinstance(text, list):
                text = text[0].get("text", "") if len(text) else ""
            tool_calls = msg.get("tool_calls", [])
            name = msg.get("name", "")

            match role := msg.get("type", "unknown"):
                case "human":
                    with (
                        st.chat_message("human"),
                        st.expander(text[:20] + "...", expanded=False),
                    ):
                        st.markdown(text or "(empty message)")
                        with st.popover("Full message"):
                            st.write(msg)
                case "ai":
                    expander_text = (
                        text[:20] + "..."
                        if text
                        else f"Tool(s) called: `{"`, `".join(tc["name"] for tc in tool_calls)}`"
                        if tool_calls
                        else "(empty message)"
                    )
                    with st.chat_message("ai"), st.expander(expander_text, expanded=False):
                        st.write(text or tool_calls)
                        with st.popover("Full message"):
                            st.write(msg)
                case "tool":
                    with (
                        st.chat_message("ai", avatar="⚙️"),
                        st.expander(f"Tool `{name}`", expanded=False),
                    ):
                        st.write(text or "(empty message)")
                        with st.popover("Full message"):
                            st.write(msg)
        except Exception as e:
            with st.expander(f"Error processing message {idx}", expanded=False):
                st.error(f"Error processing message: {e}")
                st.write(msg)


def render_manual_page() -> None:
    """Manual run: user uploads files, defines output schema, runs agent once."""
    st.title("Manual Agent Run")
    st.write("Upload files, define the output schema, and run the agent.")

    # Default schema: two empty columns
    if "output_schema" not in st.session_state:
        st.session_state["output_schema"] = [
            {"name": "Column 1", "description": ""},
            {"name": "Column 2", "description": ""},
        ]

    with st.sidebar:
        st.header("Configuration")
        model_name = "anthropic:claude-sonnet-4-6" #"google_genai:gemini-3-pro-preview"

    st.subheader("Input files")
    uploaded_files = st.file_uploader(
        "Upload one or more files (CSV/Excel/text or mixed)",
        accept_multiple_files=True,
        key="manual_input_files",
    )

    st.subheader("Additional instructions")
    use_additional_instructions = st.toggle(
        "Send additional instructions",
        value=False,
        key="manual_use_additional_instructions",
    )
    additional_instructions = st.text_area(
        "Guidance for the agent",
        help="Describe constraints, extraction rules, and expected output behavior.",
        key="manual_additional_instructions",
        disabled=not use_additional_instructions,
    )

    st.subheader("Output schema")
    schema_rows = st.session_state.get("output_schema", [])

    add_col, remove_col = st.columns(2)
    with add_col:
        if st.button("Add column", key="manual_add_column"):
            schema_rows.append({"name": "", "description": ""})
    with remove_col:
        if (
            st.button("Remove last column", key="manual_remove_column")
            and len(schema_rows) > 1
        ):
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

    # On run: save uploads to temp dir, call process_data, store result in session
    if run_clicked:
        output_columns = _build_output_columns()
        if not output_columns:
            st.error("Please define at least one output column (with a name).")
        elif not uploaded_files:
            st.error("Please upload at least one input file.")
        else:
            with st.spinner("Running agent... this may take a few minutes."):
                try:
                    with tempfile.TemporaryDirectory() as upload_root:
                        input_paths: List[Path] = []
                        for i, uploaded in enumerate(uploaded_files):
                            destination = Path(upload_root) / uploaded.name
                            counter = 1
                            while destination.exists():
                                destination = (
                                    Path(upload_root)
                                    / f"{destination.stem}_{counter}{destination.suffix}"
                                )
                                counter += 1
                            destination.write_bytes(uploaded.getvalue())
                            input_paths.append(destination)

                        result_df, messages = process_data(  # Single agent run
                            input_files=input_paths,
                            output_columns=output_columns,
                            additional_instructions=(additional_instructions or None)
                            if use_additional_instructions
                            else None,
                            model_name=model_name,
                        )
                except Exception as exc:
                    st.error(f"Agent run failed: {exc}")
                    raise
                else:
                    st.session_state["manual_result_df"] = result_df
                    st.session_state["manual_messages"] = messages

    # Show output + download when run completed
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

    _render_message_panel(st.session_state.get("manual_messages", []))


def render_test_case_page(case_key: str) -> None:
    """Generic test-case page: loads preset inputs, single run, shows output. Used for UC1, UC3–UC6."""
    config = TEST_CASES[case_key]
    state_prefix = f"{case_key}_state"

    st.title(config.title)
    st.write(config.description)

    with st.sidebar:
        st.header("Run configuration")
        model_name = "google_genai:gemini-3-pro-preview"
        variant = st.radio(
            "Scenario",
            options=["small", "medium", "large"],
            format_func=lambda v: {
                "small": "Small debug set",
                "medium": "Medium (20 rows)",
                "large": "Large batch (100 rows)",
            }.get(v, v),
            key=f"{state_prefix}_variant",
        )

    loaded_inputs = load_variant_input_files(case_key, variant)

    st.subheader("Inputs")
    for label, path, df in loaded_inputs:
        with st.expander(f"{label} ({len(df)} rows) - {path.name}", expanded=False):
            st.dataframe(df)

    st.subheader("Target output schema")
    st.dataframe(pd.DataFrame(config.output_columns))

    use_additional_instructions = st.toggle(
        "Send additional instructions",
        value=False,
        key=f"{state_prefix}_use_instructions",
    )
    additional_instructions = st.text_area(
        "Additional instructions",
        value=config.additional_instructions,
        key=f"{state_prefix}_instructions",
        height=120,
        disabled=not use_additional_instructions,
    )

    run_clicked = st.button("Run this test case", type="primary", key=f"{state_prefix}_run")
    if run_clicked:  # Single run on full input
        input_paths = [path for _, path, _ in loaded_inputs]
        with st.spinner("Running agent... this may take a few minutes."):
            try:
                result_df, messages = process_data(
                    input_files=input_paths,
                    output_columns=config.output_columns,
                    additional_instructions=(additional_instructions or None)
                    if use_additional_instructions
                    else None,
                    model_name=model_name,
                )
            except Exception as exc:
                st.error(f"Agent run failed: {exc}")
                raise
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

    _render_message_panel(st.session_state.get(f"{state_prefix}_messages", []))


def render_uc2_page() -> None:
    """
    UC2 Packshot Dimensions: single run for small, two-phase for large.
    Phase 1: sample (5 rows) -> validate/edit -> Phase 2: remaining rows with sample as reference.
    """
    config = TEST_CASES["uc2_packshot_dimensions"]
    state_prefix = "uc2_packshot_dimensions_state"

    st.title(config.title)
    st.write(config.description)

    with st.sidebar:
        st.header("Run configuration")
        model_name = "google_genai:gemini-3-pro-preview"
        variant = st.radio(
            "Scenario",
            options=["small", "medium", "large"],
            format_func=lambda v: {
                "small": "Small debug set",
                "medium": "Medium (20 rows)",
                "large": "Large batch (100 rows) - two-phase scaling",
            }.get(v, v),
            key=f"{state_prefix}_variant",
        )

    loaded_inputs = load_variant_input_files("uc2_packshot_dimensions", variant)

    st.subheader("Inputs")
    for label, path, df in loaded_inputs:
        with st.expander(f"{label} ({len(df)} rows) - {path.name}", expanded=False):
            st.dataframe(df)

    st.subheader("Target output schema")
    st.dataframe(pd.DataFrame(config.output_columns))

    use_additional_instructions = st.toggle(
        "Send additional instructions",
        value=False,
        key=f"{state_prefix}_use_instructions",
    )
    additional_instructions = st.text_area(
        "Additional instructions",
        value=config.additional_instructions,
        key=f"{state_prefix}_instructions",
        height=120,
        disabled=not use_additional_instructions,
    )

    # Small and medium: single run (no two-phase)
    if variant in ("small", "medium"):
        run_clicked = st.button(
            "Run this test case", type="primary", key=f"{state_prefix}_run"
        )
        if run_clicked:
            input_paths = [path for _, path, _ in loaded_inputs]
            with st.spinner("Running agent... this may take a few minutes."):
                try:
                    result_df, messages = process_data(
                        input_files=input_paths,
                        output_columns=config.output_columns,
                        additional_instructions=(additional_instructions or None)
                        if use_additional_instructions
                        else None,
                        model_name=model_name,
                    )
                except Exception as exc:
                    st.error(f"Agent run failed: {exc}")
                    raise
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
                file_name="uc2_packshot_dimensions_small_output.csv",
                mime="text/csv",
                key=f"{state_prefix}_download",
            )
        _render_message_panel(st.session_state.get(f"{state_prefix}_messages", []))
        return

    # Large: two-phase UI (Step 1 sample, Step 2 full batch)
    st.info(
        "Two-phase scaling: Run a sample first (5 rows), validate or edit the output, "
        "then run the full batch. The validated sample guides the agent for the remaining rows."
    )

    col1, col2 = st.columns(2)
    with col1:
        phase1_clicked = st.button(
            "Step 1: Run sample (first 5 rows)",
            type="primary",
            key=f"{state_prefix}_phase1_run",
        )
    with col2:
        phase1_done = f"{state_prefix}_phase1_df" in st.session_state  # Enable Step 2 after Phase 1
        phase2_clicked = st.button(
            "Step 2: Run full batch (remaining rows)",
            type="primary",
            key=f"{state_prefix}_phase2_run",
            disabled=not phase1_done,
            help="Complete Step 1 and validate the sample output first.",
        )

    if phase1_clicked:  # Run Phase 1: first 5 rows
        input_path = loaded_inputs[0][1]
        with st.spinner("Running sample (5 rows)... this may take a few minutes."):
            try:
                phase1_df, _, phase1_msgs, _ = process_data_two_phase(
                    input_path=input_path,
                    output_columns=config.output_columns,
                    additional_instructions=(additional_instructions or None)
                    if use_additional_instructions
                    else None,
                    model_name=model_name,
                    sample_size=5,
                    validated_phase1_df=None,
                )
                st.session_state[f"{state_prefix}_phase1_df"] = phase1_df
                st.session_state[f"{state_prefix}_phase1_messages"] = phase1_msgs
                st.session_state[f"{state_prefix}_phase2_df"] = None
                st.session_state[f"{state_prefix}_phase2_messages"] = []
            except Exception as exc:
                st.error(f"Phase 1 failed: {exc}")
                raise

    if f"{state_prefix}_phase1_df" in st.session_state:
        # Editable table: user can fix extraction errors before Phase 2
        st.subheader("Phase 1 output (validate or edit before Step 2)")
        edited = st.data_editor(
            st.session_state[f"{state_prefix}_phase1_df"],
            key=f"{state_prefix}_phase1_editor",
            use_container_width=True,
        )
        st.session_state[f"{state_prefix}_validated_phase1_df"] = edited  # May include edits

    if phase2_clicked and f"{state_prefix}_validated_phase1_df" in st.session_state:
        # Run Phase 2: remaining rows, passing validated sample as example_output_path
        validated_df = st.session_state[f"{state_prefix}_validated_phase1_df"]
        input_path = loaded_inputs[0][1]
        with st.spinner(
            "Running full batch (remaining rows)... this may take several minutes."
        ):
            try:
                _, phase2_df, _, phase2_msgs = process_data_two_phase(
                    input_path=input_path,
                    output_columns=config.output_columns,
                    additional_instructions=(additional_instructions or None)
                    if use_additional_instructions
                    else None,
                    model_name=model_name,
                    sample_size=5,
                    validated_phase1_df=validated_df,
                )
                st.session_state[f"{state_prefix}_phase2_df"] = phase2_df
                st.session_state[f"{state_prefix}_phase2_messages"] = phase2_msgs
            except Exception as exc:
                st.error(f"Phase 2 failed: {exc}")
                raise

    if f"{state_prefix}_phase2_df" in st.session_state:
        phase2_df = st.session_state[f"{state_prefix}_phase2_df"]
        # Concat validated phase 1 + phase 2 for final output
        if phase2_df is not None and not phase2_df.empty:
            validated_df = st.session_state.get(
                f"{state_prefix}_validated_phase1_df",
                st.session_state[f"{state_prefix}_phase1_df"],
            )
            final_df = pd.concat(
                [validated_df, phase2_df],
                ignore_index=True,
            )
            st.subheader("Final output")
            st.dataframe(final_df)
            csv_bytes = final_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Download output CSV",
                data=csv_bytes,
                file_name="uc2_packshot_dimensions_large_output.csv",
                mime="text/csv",
                key=f"{state_prefix}_final_download",
            )
            _render_message_panel(
                {
                    "messages": st.session_state.get(
                        f"{state_prefix}_phase2_messages", []
                    )
                }
            )
        else:
            # No remaining rows (input had <= 5 rows): final = validated sample only
            validated_df = st.session_state.get(
                f"{state_prefix}_validated_phase1_df",
                st.session_state[f"{state_prefix}_phase1_df"],
            )
            st.subheader("Final output (sample only - no remaining rows)")
            st.dataframe(validated_df)
            csv_bytes = validated_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Download output CSV",
                data=csv_bytes,
                file_name="uc2_packshot_dimensions_large_output.csv",
                mime="text/csv",
                key=f"{state_prefix}_final_download",
            )
            _render_message_panel(
                {"messages": st.session_state.get(f"{state_prefix}_phase1_messages", [])}
            )

    # Show Phase 1 messages when Phase 2 hasn't run yet
    if f"{state_prefix}_phase1_df" in st.session_state and (
        f"{state_prefix}_phase2_df" not in st.session_state
        or st.session_state[f"{state_prefix}_phase2_df"] is None
    ):
        _render_message_panel(
            {"messages": st.session_state.get(f"{state_prefix}_phase1_messages", [])}
        )


MAX_UPLOAD_ROWS = 20


def render_upload_test_case_page(case_key: str, max_rows: int = MAX_UPLOAD_ROWS) -> None:
    """
    Upload-based test page: user uploads CSV(s), validated to max_rows.
    Uses config defaults (output_columns, additional_instructions). Single run.
    """
    config = TEST_CASES[case_key]
    state_prefix = f"upload_{case_key}_state"
    file_specs = config.variants["small"].files  # Labels from small variant

    st.title(config.title)
    st.write(config.description)
    st.caption(f"Upload your CSV file(s). Maximum {max_rows} rows per file.")

    with st.sidebar:
        st.header("Run configuration")
        model_name = "google_genai:gemini-3-pro-preview"

    # File uploaders
    uploaded_data: List[tuple[str, object, pd.DataFrame]] = []  # (label, file, df)
    for i, spec in enumerate(file_specs):
        up = st.file_uploader(
            spec.label,
            type=["csv"],
            key=f"{state_prefix}_upload_{i}",
        )
        if up:
            try:
                df = pd.read_csv(up)
                uploaded_data.append((spec.label, up, df))
                with st.expander(f"{spec.label} ({len(df)} rows)", expanded=False):
                    st.dataframe(df)
            except Exception as e:
                st.error(f"Could not read {spec.label} as CSV: {e}")

    st.subheader("Target output schema")
    st.dataframe(pd.DataFrame(config.output_columns))

    use_additional_instructions = st.toggle(
        "Send additional instructions",
        value=False,
        key=f"{state_prefix}_use_instructions",
    )
    additional_instructions = st.text_area(
        "Additional instructions",
        value=config.additional_instructions,
        key=f"{state_prefix}_instructions",
        height=120,
        disabled=not use_additional_instructions,
    )
    effective_instructions = (
        (additional_instructions or config.additional_instructions)
        if use_additional_instructions
        else config.additional_instructions
    )

    run_clicked = st.button("Run this test case", type="primary", key=f"{state_prefix}_run")
    if run_clicked:
        if len(uploaded_data) != len(file_specs):
            st.error(
                f"Please upload {len(file_specs)} file(s): "
                + ", ".join(s.label for s in file_specs)
            )
        else:
            # Validate row count
            for label, up, df in uploaded_data:
                if len(df) > max_rows:
                    st.error(
                        f"{label}: {len(df)} rows. Maximum allowed is {max_rows} rows."
                    )
                    run_clicked = False
                    break
            else:
                with tempfile.TemporaryDirectory() as tmp:
                    paths = [Path(tmp) / f"input_{i}.csv" for i in range(len(uploaded_data))]
                    for (_, up, _), p in zip(uploaded_data, paths):
                        up.seek(0)
                        p.write_bytes(up.getvalue())
                    with st.spinner("Running agent... this may take a few minutes."):
                        try:
                            result_df, messages = process_data(
                                input_files=paths,
                                output_columns=config.output_columns,
                                additional_instructions=effective_instructions,
                                model_name=model_name,
                            )
                            st.session_state[f"{state_prefix}_result_df"] = result_df
                            st.session_state[f"{state_prefix}_messages"] = messages
                        except Exception as exc:
                            st.error(f"Agent run failed: {exc}")
                            raise

    if f"{state_prefix}_result_df" in st.session_state:
        result_df = st.session_state[f"{state_prefix}_result_df"]
        st.success("Agent run completed.")
        st.subheader("Output")
        st.dataframe(result_df)
        st.download_button(
            label="Download output CSV",
            data=result_df.to_csv(index=False).encode("utf-8"),
            file_name=f"{case_key}_upload_output.csv",
            mime="text/csv",
            key=f"{state_prefix}_download",
        )

    _render_message_panel(st.session_state.get(f"{state_prefix}_messages", []))
