def sanitize_text(text: str | None) -> str | None:
    """
    Sanitize text to be safe for database storage.
    Removes surrogate characters and null bytes.
    """
    if text is None:
        return None
    
    # Remove null bytes
    if "\x00" in text:
        text = text.replace("\x00", "")
        
    # Remove surrogates by encoding to utf-8 with 'ignore' and decoding back
    try:
        return text.encode('utf-8', 'ignore').decode('utf-8')
    except Exception:
        # Fallback for extremely weird cases, though the above should catch surrogates
        return "".join(c for c in text if c.isprintable())
