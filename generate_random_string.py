#!/usr/bin/env python3
"""
Generate a random alphanumeric string of specified length.
Default length is 32 characters if no input is provided.
"""

import secrets
import string


def generate_random_string(length=32):
    """Generate a random string of specified length using letters and digits."""
    characters = string.ascii_letters + string.digits
    return ''.join(secrets.choice(characters) for _ in range(length))


def main():
    print("Random String Generator")
    print("-" * 40)
    print("Common sizes: 32, 64, 128")
    print("Press Enter for default (32)")
    print()
    
    user_input = input("Enter desired string length: ").strip()
    
    # Default to 32 if empty input
    if not user_input:
        length = 32
        print(f"Using default length: {length}")
    else:
        try:
            length = int(user_input)
            if length <= 0:
                print("Error: Length must be positive. Using default (32)")
                length = 32
        except ValueError:
            print("Error: Invalid input. Using default (32)")
            length = 32
    
    print()
    random_string = generate_random_string(length)
    print(f"Generated {length}-character string:")
    print(random_string)


if __name__ == "__main__":
    main()
