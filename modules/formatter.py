def splitter(text, chunk_size=4096):
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
