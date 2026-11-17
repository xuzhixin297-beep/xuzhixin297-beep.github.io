from translator import translate_text


def main():
    sample = (
        "The cycloid is the curve traced by a fixed point "
        "on the circumference of a circle as it rolls "
        "along a straight line without slipping."
    )

    print("Original:")
    print(sample)

    print("\nTranslation:")
    translated = translate_text(sample)

    print(translated)


if __name__ == "__main__":
    main()