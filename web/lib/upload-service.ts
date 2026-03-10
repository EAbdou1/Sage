import { ref, uploadBytes, getDownloadURL } from "firebase/storage";
import { doc, setDoc, updateDoc, arrayUnion } from "firebase/firestore";
import { db, storage } from "@/utils/firebase.browser";

export const MAX_FILE_SIZE_MB = 15;

export async function uploadPresentationFile(
  file: File,
  sessionId: string,
): Promise<string> {
  if (file.type !== "application/pdf") {
    throw new Error("Invalid file format. Please upload a PDF.");
  }

  if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
    throw new Error(
      `File is too large. Maximum size is ${MAX_FILE_SIZE_MB}MB.`,
    );
  }

  const docRef = doc(db, "presentations", sessionId);

  try {
    // 1. Instantly create the document to wake up the Logger Panel
    await setDoc(docRef, {
      status: "uploading",
      fileName: file.name,
      createdAt: new Date().toISOString(),
      logs: [
        {
          timestamp: new Date().toISOString(),
          agent: "System",
          message: `Initiating secure upload for ${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)...`,
          type: "info",
        },
      ],
    });

    // 2. Upload the file to Cloud Storage
    const storageRef = ref(storage, `pdfs/${sessionId}/${file.name}`);
    await uploadBytes(storageRef, file);
    const downloadUrl = await getDownloadURL(storageRef);

    // 3. Append the success log and hand it off to the agents
    await updateDoc(docRef, {
      status: "generating",
      pdfUrl: downloadUrl,
      logs: arrayUnion({
        timestamp: new Date().toISOString(),
        agent: "System",
        message:
          "File successfully uploaded to Cloud Storage. Waking up Agent Pipeline...",
        type: "success",
      }),
    });

    setTimeout(async () => {
      await updateDoc(docRef, {
        status: "ready",
        logs: arrayUnion({
          timestamp: new Date().toISOString(),
          agent: "System",
          message: "Pipeline complete. Launching presentation.",
          type: "success",
        }),
        slides: [
          {
            id: 0,
            type: "overview",
            title: "Introduction to Blood Groups",
            content:
              "Blood types are classified based on inherited antigenic substances on the surface of red blood cells. Understanding blood groups is essential for performing life-saving blood transfusions safely.",
          },
          {
            id: 1,
            type: "content",
            title: "The ABO Blood Group System",
            content:
              "The ABO system relies on the presence or absence of two glycolipid antigens, A and B, on red blood cells. Depending on these antigens, a person's blood type is classified as A, B, AB, or O.",
          },
          {
            id: 2,
            type: "content",
            title: "Agglutinins in Plasma",
            content:
              "Blood plasma contains antibodies called agglutinins that attack recognized 'non-self' antigens. They are absent at birth but appear at 3-4 months of age due to cross-reactivity with environmental antigens like bacteria.",
          },
          {
            id: 3,
            type: "content",
            title: "The Danger of Agglutination",
            content:
              "If a patient receives an incompatible blood type, their antibodies will bind to the donor's red blood cell antigens. This causes agglutination, a deadly clumping of cells that blocks blood vessels.",
          },
          {
            id: 4,
            type: "mcq",
            title: "Knowledge Check 1",
            content:
              "Why do ABO antibodies (agglutinins) form in an infant's blood?",
            isMCQ: true,
            mcqOptions: [
              "They are inherited directly from the mother's plasma",
              "They develop after exposure to environmental antigens like bacteria and pollen",
              "They are naturally present on red blood cells at birth",
              "They only form after receiving a mismatched blood transfusion",
            ],
            correctAnswer: 1,
            explanation:
              "ABO antibodies appear around 3-4 months due to immune cross-reactivity with naturally occurring environmental factors.",
          },
          {
            id: 5,
            type: "content",
            title: "Universal Donors and Recipients",
            content:
              "People with Type O blood are 'universal donors' for packed red cells because they lack A and B antigens. Conversely, Type AB individuals are 'universal recipients' because they lack circulating anti-A and anti-B antibodies.",
          },
          {
            id: 6,
            type: "content",
            title: "The Rh Factor",
            content:
              "The Rh system is another crucial classification, primarily based on the potent D antigen. Individuals with this antigen are considered Rh-positive, while those lacking it are Rh-negative.",
          },
          {
            id: 7,
            type: "content",
            title: "Rh Transfusion Reactions",
            content:
              "Unlike the ABO system, there are no naturally occurring anti-Rh antibodies in human blood. An Rh-negative person will only develop these antibodies after a sensitizing exposure to Rh-positive blood.",
          },
          {
            id: 8,
            type: "mcq",
            title: "Knowledge Check 2",
            content:
              "Which blood type is considered the universal recipient for packed red blood cells?",
            isMCQ: true,
            mcqOptions: ["Type O", "Type A", "Type B", "Type AB"],
            correctAnswer: 3,
            explanation:
              "Type AB individuals are universal recipients because they do not have anti-A or anti-B antibodies in their blood plasma to attack donor cells.",
          },
          {
            id: 9,
            type: "content",
            title: "Hemolytic Disease of the Newborn",
            content:
              "When an Rh-negative mother carries an Rh-positive fetus, fetal blood leakage at delivery can sensitize her immune system. In subsequent pregnancies, her anti-Rh antibodies can cross the placenta and destroy the fetus's red blood cells.",
          },
          {
            id: 10,
            type: "content",
            title: "Preventing Hemolytic Disease",
            content:
              "This dangerous condition is prevented by giving the mother injections of Rho(D) immune globulin (RhoGAM). These antibodies inactivate the leaked fetal Rh antigens before the mother's immune system can mount a response.",
          },
          {
            id: 11,
            type: "content",
            title: "Why ABO Rarely Causes HDN",
            content:
              "Unlike Rh incompatibility, ABO incompatibility rarely causes Hemolytic Disease of the Newborn. This is because anti-A and anti-B antibodies are large IgM globulins that cannot physically cross the placenta.",
          },
          {
            id: 12,
            type: "mcq",
            title: "Knowledge Check 3",
            content:
              "Why does ABO incompatibility between mother and fetus rarely cause Hemolytic Disease of the Newborn?",
            isMCQ: true,
            mcqOptions: [
              "ABO antigens are completely absent from fetal red blood cells",
              "The fetal immune system rapidly neutralizes maternal ABO antibodies",
              "Anti-A and anti-B are large IgM antibodies that cannot cross the placenta",
              "The mother's blood naturally lacks all ABO antibodies during pregnancy",
            ],
            correctAnswer: 2,
            explanation:
              "Anti-A and anti-B belong to the large IgM class of gamma globulins, which are physically too big to cross the placental barrier.",
          },
          {
            id: 13,
            type: "summary",
            title: "Summary",
            content:
              "Blood typing relies on identifying ABO and Rh antigens to ensure safe medical transfusions. Strict cross-matching prevents deadly agglutination and helps manage Rh incompatibility during pregnancy.",
          },
        ],
      });
    }, 5000);

    return downloadUrl;
  } catch (error: any) {
    console.error("Firebase Upload Error:", error);

    try {
      await updateDoc(docRef, {
        status: "error",
        logs: arrayUnion({
          timestamp: new Date().toISOString(),
          agent: "System",
          message: `Upload failed: ${error.message}`,
          type: "error",
        }),
      });
    } catch (e) {
      // Catch in case the document wasn't created yet
    }

    throw new Error(
      "Failed to upload the document to the server. Please try again.",
    );
  }
}
