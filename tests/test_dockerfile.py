import os
import unittest


class DockerfileTests(unittest.TestCase):
    def test_ca_certificates_updated(self):
        dockerfile_path = os.path.join(os.path.dirname(__file__), "..", "Dockerfile")
        with open(dockerfile_path, "r", encoding="utf-8") as dockerfile:
            content = dockerfile.read()
        self.assertIn("update-ca-certificates", content)
        self.assertIn("SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt", content)
        self.assertIn("REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt", content)


if __name__ == "__main__":
    unittest.main()
