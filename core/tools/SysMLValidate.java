import org.omg.sysml.interactive.SysMLInteractive;
import org.omg.sysml.interactive.SysMLInteractiveResult;
import org.eclipse.xtext.validation.Issue;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

/**
 * A SysML v2 model checked by the OMG pilot implementation (third_party/sysml-v2-pilot): parsed, every name
 * resolved against the standard library, every rule of the language checked. Run in Java's single-file mode by
 * core/tools/sysml_tools.py:
 *
 *     java -cp "third_party/sysml-v2-pilot/*" core/tools/SysMLValidate.java <absolute library dir>/ <model.sysml>
 *
 * Prints one line per issue, "ISSUE\t<kind>\t<line>\t<message>", then "COUNTS\t<syntax>\t<semantic>\t<warnings>".
 * The library directory must be absolute: a relative one is read through URIs that keep its spaces escaped.
 */
public class SysMLValidate {
    public static void main(String[] args) throws Exception {
        SysMLInteractive sysml = SysMLInteractive.getInstance();
        sysml.loadLibrary(args[0]);
        SysMLInteractiveResult result = sysml.process(Files.readString(Path.of(args[1])));
        print("syntax", result.getSyntaxErrors());
        print("semantic", result.getSemanticErrors());
        print("warning", result.getWarnings());
        if (result.getException() != null) {
            System.out.println("EXCEPTION\t" + result.formatException().replace('\n', ' '));
        }
        System.out.println("COUNTS\t" + result.getSyntaxErrors().size() + "\t" + result.getSemanticErrors().size()
            + "\t" + result.getWarnings().size());
    }

    private static void print(String kind, List<Issue> issues) {
        for (Issue issue : issues) {
            System.out.println("ISSUE\t" + kind + "\t" + issue.getLineNumber() + "\t"
                + String.valueOf(issue.getMessage()).replace('\n', ' ').replace('\t', ' '));
        }
    }
}
