import re

import pandas as pd
import streamlit as st


IMAGE_URL_RE = re.compile(
    r"^https?://\S+\.(?:png|jpe?g|gif|webp|bmp|svg)(?:\?\S*)?(?:#\S*)?$",
    re.IGNORECASE,
)


def _is_image_url(value: str) -> bool:
    return bool(IMAGE_URL_RE.match(value.strip()))


def _build_column_config(df: pd.DataFrame) -> dict[str, st.column_config.ImageColumn]:
    column_config: dict[str, st.column_config.ImageColumn] = {}
    for column in df.columns:
        values = df[column].dropna()
        if values.empty:
            continue

        text_values = values.astype(str).str.strip()
        text_values = text_values[text_values != ""]
        if text_values.empty:
            continue

        if text_values.map(_is_image_url).all():
            column_config[column] = st.column_config.ImageColumn(column)

    return column_config


st.set_page_config(page_title="CSV Image Viewer", layout="wide")
st.title("CSV Image Viewer")
st.write("Upload a CSV file and image URL columns will render as images.")

uploaded_csv = st.file_uploader("Upload a CSV file", type=["csv"])

if uploaded_csv is None:
    st.info("Choose a CSV file to preview it.")
else:
    try:
        dataframe = pd.read_csv(uploaded_csv)
    except Exception as exc:
        st.error(f"Could not read CSV: {exc}")
    else:
        column_config = _build_column_config(dataframe)
        if column_config:
            st.caption(
                f"Detected image URL columns: {', '.join(column_config.keys())}"
            )
        else:
            st.caption("No image URL columns detected.")

        st.dataframe(
            dataframe,
            column_config=column_config,
            use_container_width=True,
        )
